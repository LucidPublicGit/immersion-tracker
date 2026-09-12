--[[
  immersion-tracker.lua — log completed mpv watches to Immersion Tracker

  On end-file (eof, or quit/stop with high watch ratio), appends a JSONL line
  and optionally POSTs the same payload to Immersion Tracker.

  Install
  -------
  Copy or symlink into an mpv scripts directory, e.g.:
    Windows:  %APPDATA%/mpv/scripts/immersion-tracker.lua
    Linux:    ~/.config/mpv/scripts/immersion-tracker.lua

  Environment / script-opts (mpv.conf script-opts/immersion-tracker.conf)
  ----------------------------------------------------------------------
    history_path     JSONL output path (default: ~~/immersion-tracker.jsonl
                     which expands under the mpv config dir)
    tracker_url      POST URL (default: http://127.0.0.1:8000/api/webhooks/mpv)
    webhook_secret   X-Webhook-Secret header (or env IMMERSION_WEBHOOK_SECRET)
    completion       ratio threshold to log on quit/stop (default: 0.90)
    min_watched      minimum watched seconds (default: 60)
    enable_http      yes/no POST to tracker (default: yes)
    enable_file      yes/no append JSONL (default: yes)

  Env overrides (when set):
    MPV_HISTORY_PATH
    IMMERSION_TRACKER_URL
    IMMERSION_WEBHOOK_SECRET
]]

local mp = require "mp"
local msg = require "mp.msg"
local utils = require "mp.utils"
local options = require "mp.options"

local o = {
    history_path = "",
    tracker_url = "http://127.0.0.1:8000/api/webhooks/mpv",
    webhook_secret = "",
    completion = 0.90,
    min_watched = 60,
    enable_http = "yes",
    enable_file = "yes",
}
options.read_options(o, "immersion-tracker")

local peak_pos = 0
local last_duration = 0

local function env_or(name, fallback)
    local v = os.getenv(name)
    if v and v ~= "" then
        return v
    end
    return fallback
end

local function truthy(s)
    s = tostring(s or ""):lower()
    return s == "1" or s == "true" or s == "yes" or s == "on"
end

local function json_escape(s)
    s = tostring(s or "")
    s = s:gsub("\\", "\\\\")
    s = s:gsub('"', '\\"')
    s = s:gsub("\n", "\\n")
    s = s:gsub("\r", "\\r")
    s = s:gsub("\t", "\\t")
    return s
end

local function iso_utc_now()
    -- Lua os.date("!") is UTC
    return os.date("!%Y-%m-%dT%H:%M:%SZ")
end

local function expand_path(p)
    if not p or p == "" then
        return p
    end
    local ok, expanded = pcall(mp.command_native, { "expand-path", p })
    if ok and expanded and expanded ~= "" then
        return expanded
    end
    return p
end

local function history_path()
    local from_env = env_or("MPV_HISTORY_PATH", "")
    if from_env and from_env ~= "" then
        return from_env
    end
    if o.history_path and o.history_path ~= "" then
        return expand_path(o.history_path)
    end
    return expand_path("~~/immersion-tracker.jsonl")
end

local function tracker_url()
    return env_or("IMMERSION_TRACKER_URL", o.tracker_url)
end

local function webhook_secret()
    return env_or("IMMERSION_WEBHOOK_SECRET", o.webhook_secret or "")
end

local function build_payload(reason)
    local path = mp.get_property("path") or ""
    local title = mp.get_property("media-title") or ""
    local duration = tonumber(mp.get_property("duration")) or last_duration or 0
    local pos = peak_pos
    local time_pos = tonumber(mp.get_property("time-pos"))
    if time_pos and time_pos > pos then
        pos = time_pos
    end
    if duration <= 0 then
        return nil, "no duration"
    end
    if pos < 0 then
        pos = 0
    end
    if pos > duration then
        pos = duration
    end
    local ratio = pos / duration
    local finished = iso_utc_now()

    -- Prefer native JSON if available (mpv 0.36+)
    local obj = {
        path = path,
        title = title,
        duration_seconds = duration,
        watched_seconds = pos,
        ratio = ratio,
        finished_at = finished,
        event = "end-file:" .. tostring(reason or ""),
    }
    local body
    if utils.format_json then
        body = utils.format_json(obj)
    else
        body = string.format(
            '{"path":"%s","title":"%s","duration_seconds":%.3f,"watched_seconds":%.3f,"ratio":%.6f,"finished_at":"%s","event":"end-file:%s"}',
            json_escape(path),
            json_escape(title),
            duration,
            pos,
            ratio,
            finished,
            json_escape(tostring(reason or ""))
        )
    end
    return {
        body = body,
        path = path,
        title = title,
        duration = duration,
        watched = pos,
        ratio = ratio,
        reason = reason,
    }
end

local function should_log(reason, ratio, watched)
    local completion = tonumber(o.completion) or 0.90
    local min_watched = tonumber(o.min_watched) or 60
    reason = tostring(reason or "")

    if watched < min_watched then
        return false, "below_min_watched"
    end
    if ratio >= completion then
        return true, "ratio"
    end
    -- Always accept clean eof (user finished the file)
    if reason == "eof" and ratio >= math.min(completion, 0.85) then
        return true, "eof"
    end
    return false, "below_threshold"
end

local function append_jsonl(payload)
    if not truthy(o.enable_file) then
        return
    end
    local hp = history_path()
    if not hp or hp == "" then
        msg.warn("[immersion-tracker] history_path empty; skip file append")
        return
    end
    local f, err = io.open(hp, "a")
    if not f then
        msg.error("[immersion-tracker] cannot open history: " .. tostring(err))
        return
    end
    f:write(payload.body)
    if not payload.body:match("\n$") then
        f:write("\n")
    end
    f:close()
    msg.info("[immersion-tracker] appended → " .. hp)
end

local function post_webhook(payload)
    if not truthy(o.enable_http) then
        return
    end
    local url = tracker_url()
    if not url or url == "" then
        return
    end
    local secret = webhook_secret()
    -- Prefer curl; available on most hosts and via Windows 10+
    local args = {
        "curl",
        "-sS",
        "-X", "POST",
        "-H", "Content-Type: application/json",
        "--connect-timeout", "3",
        "--max-time", "10",
        "-d", payload.body,
        url,
    }
    if secret and secret ~= "" then
        table.insert(args, 5, "-H")
        table.insert(args, 6, "X-Webhook-Secret: " .. secret)
    end
    local res = mp.command_native({
        name = "subprocess",
        args = args,
        playback_only = false,
        capture_stdout = true,
        capture_stderr = true,
    })
    if not res or res.error_string and res.error_string ~= "" then
        local err = res and (res.error_string or res.stderr) or "unknown"
        msg.warn("[immersion-tracker] HTTP post failed: " .. tostring(err))
        return
    end
    local status = res.status or -1
    if status ~= 0 then
        msg.warn(
            "[immersion-tracker] curl exit "
                .. tostring(status)
                .. " stderr="
                .. tostring(res.stderr or "")
        )
        return
    end
    msg.info("[immersion-tracker] posted → " .. url)
end

local function on_end_file(event)
    local reason = event and event.reason or ""
    local payload, why = build_payload(reason)
    if not payload then
        msg.verbose("[immersion-tracker] skip: " .. tostring(why))
        peak_pos = 0
        last_duration = 0
        return
    end
    local ok, why2 = should_log(reason, payload.ratio, payload.watched)
    if not ok then
        msg.verbose(
            string.format(
                "[immersion-tracker] skip %s ratio=%.3f watched=%.1f (%s)",
                tostring(reason),
                payload.ratio,
                payload.watched,
                tostring(why2)
            )
        )
        peak_pos = 0
        last_duration = 0
        return
    end
    msg.info(
        string.format(
            "[immersion-tracker] log %s ratio=%.3f watched=%.1fs %s",
            tostring(reason),
            payload.ratio,
            payload.watched,
            payload.path
        )
    )
    append_jsonl(payload)
    post_webhook(payload)
    peak_pos = 0
    last_duration = 0
end

mp.observe_property("time-pos", "number", function(_, val)
    if val and val > peak_pos then
        peak_pos = val
    end
end)

mp.observe_property("duration", "number", function(_, val)
    if val and val > 0 then
        last_duration = val
    end
end)

mp.register_event("end-file", on_end_file)

msg.info("[immersion-tracker] loaded (history=" .. tostring(history_path()) .. ")")
