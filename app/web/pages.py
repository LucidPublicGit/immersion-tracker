"""HTML page builders for Immersion Tracker UI."""

from __future__ import annotations

from html import escape

from app import __version__
from app.core.config import get_settings
from app.web.icons import icon
from app.web.logs_ui import logs_page as _logs_page_html
from app.web.momentum_ui import MOMENTUM_CSS, MOMENTUM_JS
from app.web.progress_ui import progress_page as _progress_page_html
from app.web.queue_ui import QUEUE_JS
from app.web.reading_ui import (
    READING_CSS,
    READING_JS,
    reading_fold_html,
    reading_page as _reading_page_html,
)
from app.web.styles import SHARED_CSS, nav_html


def _tool_urls() -> dict[str, str]:
    s = get_settings()
    sheets = s.yaml_config.sheets
    tadoku = s.yaml_config.tadoku
    contest = tadoku.contest
    sheet_url = ""
    if sheets.spreadsheet_id:
        sheet_url = (
            f"https://docs.google.com/spreadsheets/d/{sheets.spreadsheet_id}/edit"
        )
    from app.tadoku.upstream import (
        TADOKU_ORIGIN,
        contest_leaderboard_page_url,
        manual_log_url,
    )

    # tadoku.app 404s bare /contests/{id}; leaderboard page is the public entry.
    contest_url = TADOKU_ORIGIN
    if contest and contest.contest_id:
        contest_url = contest_leaderboard_page_url(contest.contest_id)
    # Configured contest leaderboard (same as tadoku_contest when set)
    club_url = contest_url
    return {
        "tautulli": "http://127.0.0.1:8181",
        "plex": "http://127.0.0.1:32400/web",
        "tadoku": TADOKU_ORIGIN,
        "tadoku_contest": contest_url,
        "tadoku_club": club_url,
        "tadoku_manual": manual_log_url(),
        "sheets": sheet_url,
        "contest_name": (contest.name if contest else "") or "",
        "youtube": "https://www.youtube.com",
    }


def _shell(title: str, body: str, active: str = "", extra_css: str = "") -> str:
    urls = _tool_urls()
    nav = nav_html(
        active,
        tautulli=urls["tautulli"],
        tadoku=urls["tadoku"],
        sheets=urls["sheets"],
        plex=urls["plex"],
    )
    # Optional fonts — fall back to system stacks in CSS if blocked offline
    fonts = (
        '<link rel="preconnect" href="https://fonts.googleapis.com"/>'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>'
        '<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600;700'
        '&family=IBM+Plex+Sans:wght@400;600;700&family=IBM+Plex+Serif:wght@500;600'
        '&display=swap" rel="stylesheet"/>'
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <meta name="color-scheme" content="light"/>
  <meta name="theme-color" content="#cfc4ae"/>
  <title>{escape(title)}</title>
  <link rel="icon" type="image/png" sizes="32x32" href="/static/brand/favicon-32.png"/>
  <link rel="icon" type="image/png" sizes="16x16" href="/static/brand/favicon-16.png"/>
  <link rel="apple-touch-icon" href="/static/brand/icon-128.png"/>
  {fonts}
  <style>{SHARED_CSS}{extra_css}</style>
</head>
<body>
{nav}
{body}
</body>
</html>"""


def _queue_chrome(
    urls: dict[str, str],
    *,
    mode: str = "embed",
    full_page_link: bool = True,
) -> str:
    """Queue UI chrome for Home embed (details) or /queue page (section).

    Preserves QUEUE_JS IDs: #queue-fold, #q-count, #q-sub, #session-banner,
    #contest, #msg, #auto-chip, #groups.
    """
    full = (
        ' · <a href="/">Dashboard</a>'
        if full_page_link
        else ""
    )
    toolbar = f"""
    <p class="contest-line" id="contest"></p>
    <div id="session-banner" class="session-banner hidden" role="status"></div>
    <div class="fold-toolbar">
      <div class="inbox-ops-bar">
        <div class="process-cluster">
          <button class="primary process" type="button" onclick="processAll()">Submit ready now</button>
          <span class="auto-chip" id="auto-chip" title="Next automatic submit">auto …</span>
        </div>
        <span class="msg" id="msg" role="status" aria-live="polite"></span>
      </div>
      <span class="links">
        <a href="{escape(urls['tadoku_contest'])}" target="_blank" rel="noopener">Contest</a>
        {full}
      </span>
    </div>
    <div id="groups"></div>
    <details class="fold fold-quiet" id="quick-log-fold">
      <summary>
        <span class="chev">▶</span>
        Quick log
        <span class="sub">catalog search · one-shot → Tadoku</span>
      </summary>
      <div class="fold-body">
        <div class="card-form" style="border:0;margin:0;padding:0">
          <input type="hidden" id="ql-series" value=""/>
          <div class="row">
            <div style="position:relative">
              <label for="ql-title">Title</label>
              <input id="ql-title" placeholder="Search catalog…" autocomplete="off"
                oninput="qlOnTitleInput()" onfocus="qlEnsureIndex()" onkeydown="qlOnTitleKey(event)"/>
              <div id="ql-suggest" class="ql-suggest" hidden role="listbox"></div>
              <p class="field-hint" id="ql-hint" style="margin:0.25rem 0 0">Pick a catalog work to fill type / next ep.</p>
            </div>
            <div>
              <label for="ql-type">Type</label>
              <select id="ql-type">
                <option value="anime">anime</option>
                <option value="show">show</option>
                <option value="movie">movie</option>
                <option value="manga">manga</option>
                <option value="book">book</option>
                <option value="visual_novel">visual_novel</option>
                <option value="game">game</option>
                <option value="youtube">youtube</option>
                <option value="podcast">podcast</option>
                <option value="study">study</option>
              </select>
            </div>
          </div>
          <div class="row">
            <div>
              <label for="ql-amount">Amount</label>
              <input id="ql-amount" type="number" step="any" min="0" placeholder="24"/>
            </div>
            <div>
              <label for="ql-unit">Unit</label>
              <select id="ql-unit">
                <option value="minutes">minutes</option>
                <option value="minutes_high_density">minutes_high_density</option>
                <option value="pages">pages</option>
                <option value="comic_pages">comic_pages</option>
                <option value="characters">characters</option>
                <option value="sentences">sentences</option>
              </select>
            </div>
          </div>
          <div class="row">
            <div>
              <label for="ql-activity">Activity</label>
              <select id="ql-activity">
                <option value="">— type default —</option>
                <option value="listening">listening</option>
                <option value="reading">reading</option>
                <option value="watching">watching</option>
                <option value="study">study</option>
              </select>
            </div>
            <div>
              <label>Season / Episode</label>
              <div style="display:flex;gap:0.4rem">
                <input id="ql-season" type="number" step="1" placeholder="S" style="flex:1"/>
                <input id="ql-episode" type="number" step="1" placeholder="E" style="flex:1"/>
              </div>
            </div>
          </div>
          <div class="form-actions">
            <div class="btn-row" style="margin-left:0">
              <button type="button" class="primary process" id="ql-submit" onclick="quickLog(true)">Log &amp; submit</button>
              <button type="button" class="secondary" onclick="quickLog(false)">Queue only</button>
            </div>
          </div>
        </div>
      </div>
    </details>
"""
    if mode == "page":
        return f"""
<section class="queue-page-chrome inbox-section" id="queue-fold" aria-label="Media queue">
  <div class="fold-body" style="padding:0">
    {toolbar}
  </div>
</section>
"""
    return f"""
<details class="fold" id="queue-fold" open>
  <summary>
    <span class="chev">▶</span>
    Media queue
    <span class="count-badge zero" id="q-count">0</span>
    <span class="sub" id="q-sub">loading…</span>
  </summary>
  <div class="fold-body">
    {toolbar}
  </div>
</details>
"""


def _queue_fold_html(urls: dict[str, str], *, full_page_link: bool = True) -> str:
    """Back-compat wrapper → embed mode."""
    return _queue_chrome(urls, mode="embed", full_page_link=full_page_link)


def _recent_logs_fold_html(*, default_open: bool = False) -> str:
    """Recently submitted logs from local DB."""
    open_attr = " open" if default_open else ""
    return f"""
<details class="fold fold-recent fold-quiet" id="recent-logs-fold"{open_attr}>
  <summary>
    <span class="chev">▶</span>
    Recent Tadoku logs
    <span class="count-badge zero" id="recent-count">0</span>
    <span class="sub" id="recent-sub">local · no tadoku query</span>
  </summary>
  <div class="fold-body">
    <p class="contest-line">What this tracker recently marked as submitted (status=pushed). Local database only. Click a row to open its log on tadoku.app.</p>
    <div id="recent-logs"></div>
  </div>
</details>
"""


def _abs_fold_html(*, default_open: bool = False) -> str:
    """Audiobookshelf rolling minutes → Tadoku (mirrors GSM fold shape)."""
    open_attr = " open" if default_open else ""
    hour_parts: list[str] = []
    for h in range(24):
        sel = " selected" if h == 4 else ""
        hour_parts.append(
            f'<option value="{h}"{sel}>{_abs_hour_label(h)}</option>'
        )
    hour_opts = "".join(hour_parts)
    return f"""
<details class="fold fold-gsm fold-quiet fold-abs" id="abs-fold"{open_attr}>
  <summary>
    <span class="fold-title">Audiobookshelf</span>
    <span class="count-badge zero" id="abs-count">0</span>
    <span class="sub" id="abs-sub">minutes → Tadoku</span>
  </summary>
  <div class="fold-body abs-body">
    <div id="abs-banner" class="gsm-banner abs-banner" role="status">Checking Audiobookshelf…</div>

    <div class="abs-timeline" id="abs-timeline" hidden>
      <div class="abs-timeline-labels">
        <div class="abs-tl-side">
          <span class="abs-tl-k">Last logged</span>
          <span class="abs-tl-v" id="abs-last-logged">—</span>
        </div>
        <div class="abs-tl-side abs-tl-right">
          <span class="abs-tl-k">Now</span>
          <span class="abs-tl-v" id="abs-now">—</span>
        </div>
      </div>
      <div class="abs-bar-legend" id="abs-bar-legend">
        <span><i class="abs-dot logged"></i> Already logged</span>
        <span><i class="abs-dot pending"></i> To log</span>
        <span><i class="abs-dot empty"></i> Remaining</span>
        <span class="abs-bar-total" id="abs-leg-total">0 items</span>
      </div>
    </div>

    <div class="gsm-actions abs-actions" id="abs-actions" hidden>
      <button type="button" class="primary process" id="abs-submit-btn" disabled>Log selected</button>
      <button type="button" class="secondary" id="abs-log-all-btn">Log all</button>
      <button type="button" class="secondary" id="abs-refresh-btn">Refresh</button>
    </div>
    <div id="abs-msg" class="gsm-msg" aria-live="polite"></div>

    <div class="abs-list-wrap" id="abs-table-wrap" hidden>
      <div class="abs-list-head">
        <label class="abs-select-all" title="Select all">
          <input type="checkbox" id="abs-select-all"/>
          <span>Select</span>
        </label>
        <span class="abs-list-hint" id="abs-list-hint"></span>
      </div>
      <div class="abs-list-scroll">
        <table class="abs-table">
          <colgroup>
            <col class="abs-col-check"/>
            <col class="abs-col-cover"/>
            <col class="abs-col-main"/>
            <col class="abs-col-bar"/>
            <col class="abs-col-mins"/>
            <col class="abs-col-log"/>
          </colgroup>
          <tbody id="abs-preview-rows"></tbody>
        </table>
      </div>
    </div>

    <details class="gsm-adv gsm-adv-auto" id="abs-auto">
      <summary>Auto logging</summary>
      <div class="gsm-adv-body gsm-settings">
        <p class="gsm-hint">
          Rolling listen time from Audiobookshelf sessions. Manual submit anytime;
          Auto waits for min minutes + idle; Daily dump ignores idle.
        </p>
        <section class="gsm-section">
          <div class="gsm-field-grid gsm-field-grid-cont">
            <div class="gsm-field gsm-field-mode">
              <span class="gsm-field-label" id="abs-mode-label">Mode</span>
              <div class="gsm-pref-mode" id="abs-pref-mode" role="group" aria-labelledby="abs-mode-label">
                <button type="button" data-mode="manual">Manual</button>
                <button type="button" data-mode="auto">Auto</button>
              </div>
            </div>
            <label class="gsm-field" for="abs-pref-min">
              <span class="gsm-field-label">Min minutes</span>
              <input type="number" min="0.1" step="0.5" id="abs-pref-min" value="5"/>
            </label>
            <label class="gsm-field" for="abs-pref-idle">
              <span class="gsm-field-label">Idle minutes</span>
              <input type="number" min="0" step="1" id="abs-pref-idle" value="30"/>
            </label>
          </div>
        </section>
        <section class="gsm-section">
          <div class="gsm-field-grid gsm-field-grid-daily">
            <label class="gsm-toggle gsm-toggle-compact" for="abs-pref-daily">
              <input type="checkbox" id="abs-pref-daily"/>
              <span class="gsm-toggle-text">
                <span class="gsm-toggle-title">Daily dump</span>
              </span>
            </label>
            <label class="gsm-field" for="abs-pref-hour">
              <span class="gsm-field-label">Time (local)</span>
              <select id="abs-pref-hour" aria-label="Daily auto-log hour">{hour_opts}</select>
            </label>
            <p class="gsm-tz" id="abs-tz-label"></p>
          </div>
        </section>
        <div class="gsm-settings-footer">
          <button type="button" class="secondary" id="abs-auto-save">Save auto logging</button>
        </div>
      </div>
    </details>
  </div>
</details>
"""


def _abs_hour_label(h: int) -> str:
    if h == 0:
        return "12:00 AM"
    if h < 12:
        return f"{h}:00 AM"
    if h == 12:
        return "12:00 PM"
    return f"{h - 12}:00 PM"


def _gsm_fold_html(*, default_open: bool = False) -> str:
    """GameSentenceMiner character export — Queue/Home panel (not a separate page)."""
    open_attr = " open" if default_open else ""
    return f"""
<details class="fold fold-gsm fold-quiet" id="gsm-fold"{open_attr}>
  <summary>
    <span class="chev">▶</span>
    GSM
    <span class="count-badge zero" id="gsm-count">0</span>
    <span class="sub" id="gsm-sub">characters → Tadoku</span>
  </summary>
  <div class="fold-body">
    <div id="gsm-banner" class="gsm-banner" role="status">Checking GameSentenceMiner…</div>

    <div class="gsm-stats" id="gsm-stats" hidden>
      <div class="gsm-stat">
        <div class="k">Ready to log</div>
        <div class="v" id="gsm-stat-chars">—</div>
        <div class="s" id="gsm-stat-games">—</div>
      </div>
      <div class="gsm-stat">
        <div class="k">Auto</div>
        <div class="v" id="gsm-stat-auto">—</div>
        <div class="s" id="gsm-stat-auto-sub">—</div>
      </div>
    </div>

    <div class="gsm-actions" id="gsm-actions" hidden>
      <button type="button" class="primary process" id="gsm-submit-btn"
        title="Create logs and submit them to tadoku.app now">Log to Tadoku</button>
      <button type="button" class="secondary" id="gsm-refresh-btn">Refresh</button>
    </div>
    <div id="gsm-msg" class="gsm-msg" aria-live="polite"></div>

    <div class="gsm-count-meta" id="gsm-count-meta" hidden aria-live="polite"></div>

    <div class="gsm-table-wrap" id="gsm-table-wrap" hidden>
      <table class="gsm-table">
        <thead>
          <tr>
            <th class="gsm-col-check">
              <input type="checkbox" id="gsm-select-all" checked
                title="Select / deselect all games" aria-label="Select all games"/>
            </th>
            <th>Game</th>
            <th style="text-align:right">Characters</th>
            <th class="col-hide-sm">Status</th>
          </tr>
        </thead>
        <tbody id="gsm-preview-rows"></tbody>
      </table>
    </div>

    <details class="gsm-adv" id="gsm-counting">
      <summary>Counting settings</summary>
      <div class="gsm-adv-body gsm-settings">
        <p class="gsm-hint">
          Rules for the <b>Ready to log</b> total — used by manual Log to Tadoku
          and both auto modes. Preview updates as you toggle; save to keep.
        </p>

        <div class="gsm-toggle-list" role="group" aria-label="Character counting options">
          <label class="gsm-toggle" for="gsm-pref-strip-punct">
            <input type="checkbox" id="gsm-pref-strip-punct" checked/>
            <span class="gsm-toggle-text">
              <span class="gsm-toggle-title">Strip punctuation</span>
              <span class="gsm-toggle-desc">Match GSM stats — remove punctuation, spaces, and symbols.</span>
            </span>
          </label>
          <label class="gsm-toggle" for="gsm-pref-collapse-blocks">
            <input type="checkbox" id="gsm-pref-collapse-blocks" checked/>
            <span class="gsm-toggle-text">
              <span class="gsm-toggle-title">Collapse repeated blocks</span>
              <span class="gsm-toggle-desc">Cut phrase spam inside a single line (hooks, mail loops).</span>
            </span>
          </label>
          <label class="gsm-toggle" for="gsm-pref-require-jp">
            <input type="checkbox" id="gsm-pref-require-jp" checked/>
            <span class="gsm-toggle-text">
              <span class="gsm-toggle-title">Japanese lines only</span>
              <span class="gsm-toggle-desc">Ignore clipboard URLs, code, and English (agent/clipboard noise).</span>
            </span>
          </label>
          <label class="gsm-toggle" for="gsm-pref-dedupe">
            <input type="checkbox" id="gsm-pref-dedupe"/>
            <span class="gsm-toggle-text">
              <span class="gsm-toggle-title">Skip repeated lines</span>
              <span class="gsm-toggle-desc">Count each exact line only once after the first.</span>
            </span>
          </label>
        </div>

        <p class="gsm-live-effect" id="gsm-count-effect" aria-live="polite">
          Toggle options to preview Ready to log, then save.
        </p>

        <div class="gsm-settings-footer">
          <button type="button" class="secondary" id="gsm-pref-save">Save counting</button>
          <button type="button" class="skip gsm-skip-history" id="gsm-mark-btn">
            Skip history — start from now
          </button>
        </div>
      </div>
    </details>

    <details class="gsm-adv gsm-adv-auto" id="gsm-auto">
      <summary>Auto logging</summary>
      <div class="gsm-adv-body gsm-settings">
        <p class="gsm-hint">
          Automatic Tadoku logs use the same counting rules as above.
        </p>

        <section class="gsm-section" aria-labelledby="gsm-cont-heading">
          <div class="gsm-section-head">
            <h3 class="gsm-section-title" id="gsm-cont-heading">After idle</h3>
            <p class="gsm-section-desc">
              When Auto is on, log a game once it hits the min characters and no
              new lines arrive for the idle period.
            </p>
          </div>
          <div class="gsm-field-grid gsm-field-grid-cont">
            <div class="gsm-field gsm-field-mode">
              <span class="gsm-field-label" id="gsm-mode-label">Mode</span>
              <div class="gsm-pref-mode" id="gsm-pref-mode" role="group" aria-labelledby="gsm-mode-label">
                <button type="button" data-mode="manual">Manual</button>
                <button type="button" data-mode="auto">Auto</button>
              </div>
            </div>
            <label class="gsm-field" for="gsm-pref-min">
              <span class="gsm-field-label">Min characters</span>
              <input type="number" min="1" id="gsm-pref-min" value="10000"/>
            </label>
            <label class="gsm-field" for="gsm-pref-idle">
              <span class="gsm-field-label">Idle minutes</span>
              <input type="number" min="0" step="1" id="gsm-pref-idle" value="30"/>
            </label>
          </div>
        </section>

        <section class="gsm-section" aria-labelledby="gsm-daily-heading">
          <div class="gsm-section-head">
            <h3 class="gsm-section-title" id="gsm-daily-heading">Daily dump</h3>
            <p class="gsm-section-desc">
              Once a day at the chosen local hour, log every game over the min
              (idle is ignored). Off by default.
            </p>
          </div>
          <div class="gsm-field-grid gsm-field-grid-daily">
            <label class="gsm-toggle gsm-toggle-compact" for="gsm-pref-daily">
              <input type="checkbox" id="gsm-pref-daily"/>
              <span class="gsm-toggle-text">
                <span class="gsm-toggle-title">Enabled</span>
              </span>
            </label>
            <label class="gsm-field" for="gsm-pref-hour">
              <span class="gsm-field-label">Time (local)</span>
              <select id="gsm-pref-hour" aria-label="Daily auto-log hour">
                <option value="0">12:00 AM</option>
                <option value="1">1:00 AM</option>
                <option value="2">2:00 AM</option>
                <option value="3">3:00 AM</option>
                <option value="4" selected>4:00 AM</option>
                <option value="5">5:00 AM</option>
                <option value="6">6:00 AM</option>
                <option value="7">7:00 AM</option>
                <option value="8">8:00 AM</option>
                <option value="9">9:00 AM</option>
                <option value="10">10:00 AM</option>
                <option value="11">11:00 AM</option>
                <option value="12">12:00 PM</option>
                <option value="13">1:00 PM</option>
                <option value="14">2:00 PM</option>
                <option value="15">3:00 PM</option>
                <option value="16">4:00 PM</option>
                <option value="17">5:00 PM</option>
                <option value="18">6:00 PM</option>
                <option value="19">7:00 PM</option>
                <option value="20">8:00 PM</option>
                <option value="21">9:00 PM</option>
                <option value="22">10:00 PM</option>
                <option value="23">11:00 PM</option>
              </select>
            </label>
            <p class="gsm-tz" id="gsm-tz-label"></p>
          </div>
        </section>

        <div class="gsm-settings-footer">
          <button type="button" class="secondary" id="gsm-auto-save">Save auto logging</button>
        </div>
      </div>
    </details>
  </div>
</details>
"""


def home_page() -> str:
    """Dashboard only: pulse → Inbox CTA, immersion stock, charts."""
    urls = _tool_urls()
    contest_name = escape(urls["contest_name"]) if urls["contest_name"] else "Tadoku contest"
    sheets_tile = ""
    if urls["sheets"]:
        sheets_tile = f"""
        <a class="tool-tile sheets" href="{escape(urls['sheets'])}" target="_blank" rel="noopener">
          <span class="ico">{icon("sheets")}</span>
          Google Sheets
          <span class="go">↗</span>
        </a>"""

    body = f"""
<main id="main" class="page page-wide" tabindex="-1">
  <div class="mast">
    <h1>Dashboard</h1>
    <div class="meta">
      <span class="status-dot" id="health-dot"></span>
      <span id="health-text">…</span>
      · <span id="stats-age">metrics…</span>
      · v{escape(__version__)}
      · <a href="{escape(urls['tadoku_club'])}" target="_blank" rel="noopener">Tadoku contest</a>
    </div>
  </div>

  <div class="ledger ledger-queue" aria-label="Tadoku queue pulse">
    <div class="ledger-cell priority" id="cell-pending">
      <div class="k">Pending review</div>
      <div class="v" id="s-pending">—</div>
      <div class="s">needs approve / skip</div>
    </div>
    <div class="ledger-cell priority ready-cell" id="cell-ready">
      <div class="k">Ready</div>
      <div class="v" id="s-ready">—</div>
      <div class="s">can submit</div>
    </div>
    <div class="ledger-cell" id="cell-score">
      <div class="k">Score est.</div>
      <div class="v" id="s-score">—</div>
      <div class="s">local estimate</div>
    </div>
  </div>

  <div class="dash-cta" id="dash-cta">
    <a class="primary dash-cta-btn" href="/queue" id="dash-inbox-link">Open Inbox</a>
    <span class="dash-cta-hint" id="dash-cta-hint">Clear pending media, GSM, and reading in one place</span>
    <a class="chip" href="/progress">Progress</a>
    <a class="chip" href="/race">Race</a>
    <a class="chip" href="/logs">Logs</a>
  </div>

  <span id="s-pushed" class="faint" hidden aria-hidden="true">—</span>
  <span id="s-logs" class="faint" hidden aria-hidden="true">—</span>

  <section class="immersion-panel" aria-label="Immersion totals">
    <div class="immersion-head">
      <h2>Immersion</h2>
      <span class="immersion-sub" id="immersion-sub">all-time totals</span>
    </div>
    <div class="immersion-grid" id="immersion-grid">
      <div class="immersion-card skeleton">
        <div class="ik">Listening</div>
        <div class="iv">—</div>
        <div class="iu">hours</div>
      </div>
      <div class="immersion-card skeleton">
        <div class="ik">Characters</div>
        <div class="iv">—</div>
        <div class="iu">chars</div>
      </div>
      <div class="immersion-card skeleton">
        <div class="ik">Pages</div>
        <div class="iv">—</div>
        <div class="iu">pages</div>
      </div>
    </div>
  </section>

  <details class="home-insight" id="home-insight-fold" open>
    <summary>
      <span class="chev">▶</span>
      This year
      <span class="faint" style="font-weight:500;margin-left:auto">heat map · year chart</span>
    </summary>
    <div>
      <details class="immersion-chart-fold" id="immersion-heat-fold" open>
        <summary>
          <span class="chev">▶</span>
          <span class="chart-title">Activity heat map</span>
          <span class="chart-sub" id="heat-year-sub">daily · this year</span>
        </summary>
        <div class="immersion-chart-body">
          <div class="immersion-chart-toolbar" id="heat-metric-toggles" aria-label="Heat map metric">
            <span class="hint" id="heat-metric-hint">cell intensity by selected metric</span>
          </div>
          <div class="immersion-heat-wrap">
            <div class="immersion-heat" id="immersion-heat" role="group" aria-label="Daily immersion heat map this year"></div>
            <div class="immersion-chart-tip" id="immersion-heat-tip"></div>
            <div class="immersion-chart-empty" id="immersion-heat-empty">No logs yet this year</div>
          </div>
          <div class="immersion-heat-legend" id="immersion-heat-legend">
            <span>Less</span>
            <span class="heat-swatch l0"></span>
            <span class="heat-swatch l1"></span>
            <span class="heat-swatch l2"></span>
            <span class="heat-swatch l3"></span>
            <span class="heat-swatch l4"></span>
            <span>More</span>
          </div>
        </div>
      </details>
      <details class="immersion-chart-fold" id="immersion-chart-fold">
        <summary>
          <span class="chev">▶</span>
          <span class="chart-title">Year progress</span>
          <span class="chart-sub" id="chart-year-sub">cumulative · this year</span>
        </summary>
        <div class="immersion-chart-body">
          <div class="immersion-chart-toolbar" id="chart-series-toggles" aria-label="Series toggles">
            <span class="hint" id="chart-scale-hint">lines scaled independently</span>
          </div>
          <div class="immersion-chart-wrap">
            <canvas id="immersion-canvas" aria-label="Immersion over time this year"></canvas>
            <div class="immersion-chart-tip" id="immersion-chart-tip"></div>
            <div class="immersion-chart-empty" id="immersion-chart-empty">No logs yet this year</div>
          </div>
        </div>
      </details>
    </div>
  </details>

  <details class="help-fold">
    <summary>Tools &amp; external links</summary>
    <div class="help-body">
      <div class="tool-grid">
        <a class="tool-tile plex" href="{escape(urls['plex'])}" target="_blank" rel="noopener">
          <span class="ico">{icon("plex")}</span>Plex<span class="go">↗</span>
        </a>
        <a class="tool-tile tautulli" href="{escape(urls['tautulli'])}" target="_blank" rel="noopener">
          <span class="ico">{icon("tautulli")}</span>Tautulli<span class="go">↗</span>
        </a>
        <a class="tool-tile tadoku" href="{escape(urls['tadoku_club'])}" target="_blank" rel="noopener">
          <span class="ico">{icon("contest")}</span>Tadoku contest<span class="go">↗</span>
        </a>
        <a class="tool-tile tadoku" href="{escape(urls['tadoku_manual'])}" target="_blank" rel="noopener">
          <span class="ico">{icon("manual")}</span>Manual Tadoku<span class="go">↗</span>
        </a>
        {sheets_tile}
        <a class="tool-tile youtube" href="{escape(urls['youtube'])}" target="_blank" rel="noopener">
          <span class="ico">{icon("youtube")}</span>YouTube<span class="go">↗</span>
        </a>
      </div>
      <p class="faint" style="margin:0.65rem 0 0">{contest_name}</p>
    </div>
  </details>

  <details class="help-fold">
    <summary>How this works</summary>
    <div class="help-body">
      <ul class="tips">
        <li><b>Inbox</b> is where work happens — media queue, GSM, and Hoshi reading.</li>
        <li><b>Pending</b> → Approve → <b>Ready</b> → Submit ready now.</li>
        <li>Plex watches land via <b>Tautulli</b> (≥90%). YouTube via the extension.</li>
        <li>Fix English titles in <b>Catalog</b>. Edit history on <b>Logs</b>.</li>
      </ul>
    </div>
  </details>

  <p class="footer-note">Dashboard · daily ops live on <a href="/queue">Inbox</a></p>
</main>
<script>
async function refreshMetrics() {{
  const dot = document.getElementById('health-dot');
  const ht = document.getElementById('health-text');
  try {{
    const h = await fetch('/api/health');
    if (h.ok) {{
      dot.className = 'status-dot';
      ht.textContent = 'online';
    }} else {{
      dot.className = 'status-dot warn';
      ht.textContent = 'degraded';
    }}
  }} catch (e) {{
    dot.className = 'status-dot bad';
    ht.textContent = 'offline';
  }}
  try {{
    const m = await (await fetch('/api/metrics')).json();
    const fmt = (n, d=1) => n != null ? Number(n).toLocaleString(undefined, {{maximumFractionDigits: d}}) : '—';
    const pendingN = Number(m.tadoku_pending ?? 0);
    const readyN = Number(m.tadoku_ready ?? 0);
    document.getElementById('s-pending').textContent = m.tadoku_pending ?? '—';
    document.getElementById('s-ready').textContent = m.tadoku_ready ?? '—';
    const cellP = document.getElementById('cell-pending');
    const cellR = document.getElementById('cell-ready');
    if (cellP) cellP.classList.toggle('has-work', pendingN > 0);
    if (cellR) cellR.classList.toggle('has-work', readyN > 0);
    const pushedEl = document.getElementById('s-pushed');
    if (pushedEl) pushedEl.textContent = m.tadoku_pushed ?? '—';
    document.getElementById('s-score').textContent = fmt(m.tadoku_score_estimate);
    const logsEl = document.getElementById('s-logs');
    if (logsEl) logsEl.textContent = m.total_logs ?? '—';
    const sub = document.getElementById('immersion-sub');
    if (sub) {{
      const p = m.tadoku_pushed != null ? Number(m.tadoku_pushed).toLocaleString() : '—';
      const t = m.total_logs != null ? Number(m.total_logs).toLocaleString() : '—';
      sub.textContent = `all-time · ${{p}} pushed · ${{t}} logs`;
    }}
    const hint = document.getElementById('dash-cta-hint');
    const link = document.getElementById('dash-inbox-link');
    if (pendingN + readyN > 0) {{
      if (hint) hint.textContent = `${{pendingN}} pending · ${{readyN}} ready — clear the Inbox`;
      if (link) link.textContent = 'Open Inbox · work waiting';
    }} else {{
      if (hint) hint.textContent = 'Inbox clear · media, GSM, and reading live there';
      if (link) link.textContent = 'Open Inbox';
    }}
    renderImmersion(m);
    document.getElementById('stats-age').textContent = 'updated just now';
  }} catch (e) {{
    document.getElementById('stats-age').textContent = 'metrics n/a';
  }}
}}

function renderImmersion(m) {{
  const byAct = m.by_activity || {{}};
  const byUnit = m.by_unit || {{}};
  const minuteKeys = ['minutes', 'minutes_high_density'];
  const pageKeys = ['pages', 'two_column_pages'];
  const fmtInt = (n) => Number(n).toLocaleString(undefined, {{maximumFractionDigits: 0}});
  const fmtHrs = (mins) => (mins / 60).toLocaleString(undefined, {{maximumFractionDigits: 1, minimumFractionDigits: 0}});

  // Prefer activity splits when present; fall back to unit totals
  const hasActivityData = Object.keys(byAct).length > 0;
  const listenFromAct = activityUnitSum(byAct, 'listening', minuteKeys);
  const listenMins = hasActivityData ? listenFromAct : unitSum(byUnit, minuteKeys);
  const speakMins = activityUnitSum(byAct, 'speaking', minuteKeys);
  const studyMins = activityUnitSum(byAct, 'study', minuteKeys);
  const writeChars = activityUnitSum(byAct, 'writing', ['characters']);
  const totalChars = unitSum(byUnit, ['characters']);
  const readCharsAct = activityUnitSum(byAct, 'reading', ['characters']);
  // Prefer reading chars; fall back to all non-writing chars so nothing is hidden
  const readChars = readCharsAct > 0
    ? readCharsAct
    : Math.max(0, totalChars - writeChars);
  const readPagesAct = activityUnitSum(byAct, 'reading', pageKeys);
  const readPages = readPagesAct > 0 ? readPagesAct : unitSum(byUnit, pageKeys);
  const comicPages = unitSum(byUnit, ['comic_pages']);
  const sentences = unitSum(byUnit, ['sentences']);
  // Minute-bearing activities outside listening/speaking/study
  let otherMins = 0;
  if (hasActivityData) {{
    for (const [act, units] of Object.entries(byAct)) {{
      if (['listening', 'speaking', 'study'].includes(act)) continue;
      otherMins += unitSum(units, minuteKeys);
    }}
  }}

  const cards = [
    {{
      key: 'listening', tone: 'listen',
      label: 'Listening', value: fmtHrs(listenMins), unit: 'hours',
      detail: listenMins ? `${{fmtInt(listenMins)}} min` : '',
      show: true,
    }},
    {{
      key: 'chars', tone: 'chars',
      label: 'Characters', value: fmtInt(readChars), unit: 'chars',
      detail: writeChars > 0 && readCharsAct > 0 ? 'reading' : '',
      show: true,
    }},
    {{
      key: 'pages', tone: 'pages',
      label: 'Pages', value: fmtInt(readPages), unit: 'pages',
      detail: '',
      show: true,
    }},
    {{
      key: 'comic', tone: 'comic',
      label: 'Comic pages', value: fmtInt(comicPages), unit: 'pages',
      detail: 'manga / comics',
      show: comicPages > 0,
    }},
    {{
      key: 'sentences', tone: 'sent',
      label: 'Sentences', value: fmtInt(sentences), unit: 'sentences',
      detail: '',
      show: sentences > 0,
    }},
    {{
      key: 'writing', tone: 'write',
      label: 'Writing', value: fmtInt(writeChars), unit: 'chars',
      detail: 'characters written',
      show: writeChars > 0,
    }},
    {{
      key: 'speaking', tone: 'speak',
      label: 'Speaking', value: fmtHrs(speakMins), unit: 'hours',
      detail: speakMins ? `${{fmtInt(speakMins)}} min` : '',
      show: speakMins > 0,
    }},
    {{
      key: 'study', tone: 'study',
      label: 'Study', value: fmtHrs(studyMins), unit: 'hours',
      detail: studyMins ? `${{fmtInt(studyMins)}} min` : '',
      show: studyMins > 0,
    }},
    {{
      key: 'other-time', tone: 'other',
      label: 'Other time', value: fmtHrs(otherMins), unit: 'hours',
      detail: otherMins ? `${{fmtInt(otherMins)}} min` : '',
      show: otherMins > 0,
    }},
  ].filter(c => c.show);

  const grid = document.getElementById('immersion-grid');
  if (!grid) return;
  grid.innerHTML = cards.map(c => `
    <div class="immersion-card tone-${{c.tone}}" data-key="${{c.key}}">
      <div class="ik">${{c.label}}</div>
      <div class="iv">${{c.value}}</div>
      <div class="iu">${{c.unit}}${{c.detail ? ` · ${{c.detail}}` : ''}}</div>
    </div>
  `).join('');

  const hours = m.total_hours != null
    ? Number(m.total_hours).toLocaleString(undefined, {{maximumFractionDigits: 1}})
    : fmtHrs(unitSum(byUnit, minuteKeys));
  const sub = document.getElementById('immersion-sub');
  if (sub) sub.textContent = `${{hours}} h total time · ${{m.total_logs ?? 0}} logs`;
}}

/* ── Year immersion chart + heat map (shared timeline) ── */
const CHART_OPEN_KEY = 'immersion.chart.open';
const CHART_SERIES_KEY = 'immersion.chart.series';
const HEAT_OPEN_KEY = 'immersion.heat.open';
const HEAT_METRIC_KEY = 'immersion.heat.metric';
const CHART_SERIES = [
  {{ key: 'hours', label: 'Listening', color: '#2a5278', unit: 'h', fmt: (v) => v.toLocaleString(undefined, {{maximumFractionDigits: 1}}) + ' h' }},
  {{ key: 'characters', label: 'Characters', color: '#c45c26', unit: 'chars', fmt: (v) => Math.round(v).toLocaleString() + ' chars' }},
  {{ key: 'pages', label: 'Pages', color: '#2f6b3a', unit: 'pages', fmt: (v) => v.toLocaleString(undefined, {{maximumFractionDigits: 1}}) + ' pages' }},
  {{ key: 'comic_pages', label: 'Comic', color: '#7a3d6a', unit: 'pages', fmt: (v) => v.toLocaleString(undefined, {{maximumFractionDigits: 1}}) + ' comic' }},
];
const HEAT_METRICS = [
  {{ key: 'score', label: 'Score', fmt: (v) => v.toLocaleString(undefined, {{maximumFractionDigits: 2}}) + ' pts' }},
  {{ key: 'hours', label: 'Listening', fmt: (v) => v.toLocaleString(undefined, {{maximumFractionDigits: 1}}) + ' h' }},
  {{ key: 'characters', label: 'Characters', fmt: (v) => Math.round(v).toLocaleString() + ' chars' }},
  {{ key: 'pages', label: 'Pages', fmt: (v) => v.toLocaleString(undefined, {{maximumFractionDigits: 1}}) + ' pages' }},
  {{ key: 'logs', label: 'Logs', fmt: (v) => Math.round(v).toLocaleString() + ' logs' }},
];
const chartState = {{
  data: null,
  enabled: {{ hours: true, characters: true, pages: true, comic_pages: true }},
  loaded: false,
}};
const heatState = {{
  metric: 'score',
}};

function loadChartPrefs() {{
  try {{
    const raw = localStorage.getItem(CHART_SERIES_KEY);
    if (raw) {{
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === 'object') {{
        for (const k of Object.keys(chartState.enabled)) {{
          if (typeof parsed[k] === 'boolean') chartState.enabled[k] = parsed[k];
        }}
      }}
    }}
  }} catch (e) {{ /* ignore */ }}
  try {{
    const hm = localStorage.getItem(HEAT_METRIC_KEY);
    if (hm && HEAT_METRICS.some(m => m.key === hm)) heatState.metric = hm;
  }} catch (e) {{ /* ignore */ }}

  const chartFold = document.getElementById('immersion-chart-fold');
  if (chartFold) {{
    const openPref = localStorage.getItem(CHART_OPEN_KEY);
    /* absent or '0' → closed; only '1' opens */
    chartFold.open = (openPref === '1');
    chartFold.addEventListener('toggle', () => {{
      try {{ localStorage.setItem(CHART_OPEN_KEY, chartFold.open ? '1' : '0'); }} catch (e) {{}}
      if (chartFold.open) {{
        ensureTimeline().then(() => drawImmersionChart());
      }}
    }});
  }}

  const heatFold = document.getElementById('immersion-heat-fold');
  if (heatFold) {{
    const heatPref = localStorage.getItem(HEAT_OPEN_KEY);
    /* absent or '0' → closed; only '1' opens */
    heatFold.open = (heatPref === '1');
    heatFold.addEventListener('toggle', () => {{
      try {{ localStorage.setItem(HEAT_OPEN_KEY, heatFold.open ? '1' : '0'); }} catch (e) {{}}
      if (heatFold.open) {{
        ensureTimeline().then(() => drawImmersionHeatmap());
      }}
    }});
  }}
}}

function saveSeriesPrefs() {{
  try {{ localStorage.setItem(CHART_SERIES_KEY, JSON.stringify(chartState.enabled)); }} catch (e) {{}}
}}

function renderSeriesChips() {{
  const host = document.getElementById('chart-series-toggles');
  if (!host) return;
  const hint = host.querySelector('.hint');
  host.querySelectorAll('.series-chip').forEach(el => el.remove());
  const totals = (chartState.data && chartState.data.totals) || {{}};
  for (const s of CHART_SERIES) {{
    const total = Number(totals[s.key] || 0);
    // Hide comic chip entirely when year has none (and no pending data)
    if (s.key === 'comic_pages' && chartState.loaded && total <= 0) continue;
    const on = chartState.enabled[s.key] !== false;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'series-chip ' + (on ? 'on' : 'off');
    btn.dataset.key = s.key;
    btn.innerHTML = `<span class="dot" style="background:${{s.color}}"></span>${{s.label}}`;
    if (total > 0) btn.title = s.fmt(total) + ' this year';
    btn.addEventListener('click', () => {{
      chartState.enabled[s.key] = !chartState.enabled[s.key];
      saveSeriesPrefs();
      renderSeriesChips();
      drawImmersionChart();
    }});
    host.insertBefore(btn, hint || null);
  }}
}}

function updateTimelineSubs(data) {{
  if (!data) return;
  const t = data.totals || {{}};
  const bits = [];
  if (t.hours) bits.push(Number(t.hours).toLocaleString(undefined, {{maximumFractionDigits: 1}}) + ' h');
  if (t.characters) bits.push(Math.round(t.characters).toLocaleString() + ' chars');
  if (t.pages) bits.push(Number(t.pages).toLocaleString(undefined, {{maximumFractionDigits: 0}}) + ' pages');
  const chartSub = document.getElementById('chart-year-sub');
  if (chartSub) {{
    chartSub.textContent = data.year + ' cumulative' + (bits.length ? ' · ' + bits.join(' · ') : '');
  }}
  const heatSub = document.getElementById('heat-year-sub');
  if (heatSub) {{
    const activeDays = (data.days || []).filter(d => (d.logs || 0) > 0 || (d.score || 0) > 0).length;
    heatSub.textContent = data.year + ' daily' + (activeDays ? ' · ' + activeDays + ' active days' : '');
  }}
}}

async function ensureTimeline(force) {{
  if (!force && chartState.loaded && chartState.data) return chartState.data;
  try {{
    const year = new Date().getFullYear();
    const r = await fetch('/api/metrics/timeline?year=' + year);
    if (!r.ok) throw new Error('timeline ' + r.status);
    chartState.data = await r.json();
    chartState.loaded = true;
    updateTimelineSubs(chartState.data);
    renderSeriesChips();
    renderHeatMetricChips();
    return chartState.data;
  }} catch (e) {{
    chartState.loaded = true;
    chartState.data = {{ year: new Date().getFullYear(), days: [], totals: {{}} }};
    updateTimelineSubs(chartState.data);
    renderSeriesChips();
    renderHeatMetricChips();
    return chartState.data;
  }}
}}

function saveHeatMetricPref() {{
  try {{ localStorage.setItem(HEAT_METRIC_KEY, heatState.metric); }} catch (e) {{}}
}}

function renderHeatMetricChips() {{
  const host = document.getElementById('heat-metric-toggles');
  if (!host) return;
  const hint = host.querySelector('.hint');
  host.querySelectorAll('.series-chip').forEach(el => el.remove());
  for (const m of HEAT_METRICS) {{
    const on = heatState.metric === m.key;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'series-chip ' + (on ? 'on' : 'off');
    btn.dataset.key = m.key;
    btn.innerHTML = `<span class="dot" style="background:${{on ? '#c45c26' : '#b8ad96'}}"></span>${{m.label}}`;
    btn.addEventListener('click', () => {{
      heatState.metric = m.key;
      saveHeatMetricPref();
      renderHeatMetricChips();
      drawImmersionHeatmap();
    }});
    host.insertBefore(btn, hint || null);
  }}
}}

function heatLevel(value, max) {{
  if (!(value > 0) || !(max > 0)) return 0;
  // sqrt scale spreads mid-range activity better than linear
  const t = Math.sqrt(value / max);
  if (t < 0.25) return 1;
  if (t < 0.5) return 2;
  if (t < 0.75) return 3;
  return 4;
}}

function heatMetricValue(row, key) {{
  if (!row) return 0;
  return Number(row[key]) || 0;
}}

function drawImmersionHeatmap() {{
  const host = document.getElementById('immersion-heat');
  const empty = document.getElementById('immersion-heat-empty');
  const tip = document.getElementById('immersion-heat-tip');
  if (!host) return;
  const fold = document.getElementById('immersion-heat-fold');
  if (fold && !fold.open) return;

  const data = chartState.data;
  const year = (data && data.year) || new Date().getFullYear();
  const metric = HEAT_METRICS.find(m => m.key === heatState.metric) || HEAT_METRICS[0];
  const byDate = new Map((data && data.days || []).map(d => [d.date, d]));

  // Full calendar year, weeks as columns, Sunday-first rows (GitHub-style)
  const jan1 = new Date(Date.UTC(year, 0, 1));
  const dec31 = new Date(Date.UTC(year, 11, 31));
  const today = new Date();
  const todayStr = today.getFullYear() === year
    ? new Date(Date.UTC(today.getFullYear(), today.getMonth(), today.getDate())).toISOString().slice(0, 10)
    : (today.getFullYear() < year ? '0000-00-00' : '9999-99-99');

  // Pad start so first column starts on Sunday
  const startDow = jan1.getUTCDay(); // 0=Sun
  const gridStart = new Date(jan1);
  gridStart.setUTCDate(gridStart.getUTCDate() - startDow);

  const endDow = dec31.getUTCDay();
  const gridEnd = new Date(dec31);
  gridEnd.setUTCDate(gridEnd.getUTCDate() + (6 - endDow));

  const cells = []; // {{ date|null, inYear, future, value, row }}
  for (let d = new Date(gridStart); d <= gridEnd; d.setUTCDate(d.getUTCDate() + 1)) {{
    const ds = d.toISOString().slice(0, 10);
    const inYear = d.getUTCFullYear() === year;
    const future = inYear && ds > todayStr;
    const row = byDate.get(ds);
    const value = inYear && !future ? heatMetricValue(row, metric.key) : 0;
    cells.push({{
      date: inYear ? ds : null,
      inYear,
      future,
      value,
      row,
      dow: d.getUTCDay(),
      month: d.getUTCMonth(),
    }});
  }}

  const values = cells.filter(c => c.inYear && !c.future && c.value > 0).map(c => c.value);
  const max = values.length ? Math.max(...values) : 0;
  const hasAny = max > 0;

  if (!hasAny) {{
    if (empty) empty.classList.add('show');
    host.innerHTML = '';
    if (tip) tip.style.display = 'none';
    return;
  }}
  if (empty) empty.classList.remove('show');

  // Column-major weeks
  const weeks = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));

  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  // Month labels: place at first in-year cell of each month
  const monthLabels = [];
  let lastMonth = -1;
  weeks.forEach((week, wi) => {{
    for (const c of week) {{
      if (!c.inYear || c.date == null) continue;
      if (c.month !== lastMonth) {{
        monthLabels.push({{ month: c.month, weekIndex: wi }});
        lastMonth = c.month;
      }}
      break;
    }}
  }});

  const dowLabels = ['Sun', '', 'Tue', '', 'Thu', '', 'Sat'];
  // Fit weeks into available width (horizontal scroll as fallback on narrow screens)
  const wrapEl = host.closest('.immersion-heat-wrap');
  const avail = wrapEl ? Math.max(240, wrapEl.clientWidth - 36) : 720;
  const ideal = Math.floor(avail / Math.max(weeks.length, 1)) - 3;
  const cellPx = Math.max(9, Math.min(13, ideal));
  const gapPx = cellPx <= 10 ? 2 : 3;
  const weekW = cellPx + gapPx;
  host.style.setProperty('--heat-cell', cellPx + 'px');
  host.style.setProperty('--heat-gap', gapPx + 'px');

  const monthsHtml = monthLabels.map(m => {{
    const left = m.weekIndex * weekW;
    return `<span style="left:${{left}}px">${{months[m.month]}}</span>`;
  }}).join('');

  const weeksHtml = weeks.map(week => {{
    const cellsHtml = week.map(c => {{
      if (!c.inYear) {{
        return `<span class="heat-cell future" aria-hidden="true"></span>`;
      }}
      if (c.future) {{
        return `<span class="heat-cell future" title="${{c.date}}" aria-hidden="true"></span>`;
      }}
      const level = heatLevel(c.value, max);
      const title = c.date + (c.value > 0 ? ': ' + metric.fmt(c.value) : ': none');
      return `<button type="button" class="heat-cell l${{level}}" data-date="${{c.date}}" data-value="${{c.value}}" title="${{title}}" aria-label="${{title}}"></button>`;
    }}).join('');
    return `<div class="heat-week">${{cellsHtml}}</div>`;
  }}).join('');

  const dowsHtml = dowLabels.map(l =>
    l ? `<span>${{l}}</span>` : `<span class="blank">·</span>`
  ).join('');

  host.innerHTML = `
    <div class="heat-dows">${{dowsHtml}}</div>
    <div class="heat-main">
      <div class="heat-months">${{monthsHtml}}</div>
      <div class="heat-weeks">${{weeksHtml}}</div>
    </div>
  `;

  // Hover tip with full day breakdown
  host.querySelectorAll('.heat-cell[data-date]').forEach(el => {{
    el.addEventListener('mouseenter', (ev) => {{
      if (!tip) return;
      const ds = el.dataset.date;
      const row = byDate.get(ds);
      const bits = [];
      if (row) {{
        if (row.score) bits.push(`Score: ${{Number(row.score).toLocaleString(undefined, {{maximumFractionDigits: 2}})}}`);
        if (row.hours) bits.push(`Listening: ${{Number(row.hours).toLocaleString(undefined, {{maximumFractionDigits: 1}})}} h`);
        if (row.characters) bits.push(`Chars: ${{Math.round(row.characters).toLocaleString()}}`);
        if (row.pages) bits.push(`Pages: ${{Number(row.pages).toLocaleString(undefined, {{maximumFractionDigits: 1}})}}`);
        if (row.comic_pages) bits.push(`Comic: ${{Number(row.comic_pages).toLocaleString(undefined, {{maximumFractionDigits: 1}})}}`);
        if (row.logs) bits.push(`Logs: ${{row.logs}}`);
      }}
      const body = bits.length
        ? bits.map(b => `<div class="row">${{b}}</div>`).join('')
        : `<div class="row">No immersion</div>`;
      tip.innerHTML = `<strong>${{ds}}</strong>${{body}}`;
      tip.style.display = 'block';
      const wrap = host.closest('.immersion-heat-wrap') || host;
      const wr = wrap.getBoundingClientRect();
      const er = el.getBoundingClientRect();
      const tipW = tip.offsetWidth || 160;
      const tipH = tip.offsetHeight || 60;
      let left = er.left - wr.left + er.width / 2 - tipW / 2;
      let top = er.top - wr.top - tipH - 8;
      if (left < 4) left = 4;
      if (left + tipW > wr.width - 4) left = wr.width - tipW - 4;
      if (top < 4) top = er.top - wr.top + er.height + 8;
      tip.style.left = left + 'px';
      tip.style.top = top + 'px';
    }});
    el.addEventListener('mouseleave', () => {{
      if (tip) tip.style.display = 'none';
    }});
  }});
}}

function buildYearAxis(year, sparseDays) {{
  const start = new Date(Date.UTC(year, 0, 1));
  const today = new Date();
  const endCap = new Date(Date.UTC(year, today.getUTCMonth(), today.getUTCDate()));
  const yearEnd = new Date(Date.UTC(year, 11, 31));
  const end = endCap < yearEnd ? endCap : yearEnd;
  // If no data yet, still show Jan 1 → today
  const dates = [];
  for (let d = new Date(start); d <= end; d.setUTCDate(d.getUTCDate() + 1)) {{
    dates.push(d.toISOString().slice(0, 10));
  }}
  if (!dates.length) dates.push(start.toISOString().slice(0, 10));

  const byDate = new Map((sparseDays || []).map(x => [x.date, x]));
  const daily = {{ hours: [], characters: [], pages: [], comic_pages: [] }};
  for (const ds of dates) {{
    const row = byDate.get(ds);
    daily.hours.push(row ? Number(row.hours) || 0 : 0);
    daily.characters.push(row ? Number(row.characters) || 0 : 0);
    daily.pages.push(row ? Number(row.pages) || 0 : 0);
    daily.comic_pages.push(row ? Number(row.comic_pages) || 0 : 0);
  }}
  const cum = {{}};
  for (const k of Object.keys(daily)) {{
    let run = 0;
    cum[k] = daily[k].map(v => {{ run += v; return run; }});
  }}
  return {{ dates, cum, daily }};
}}

function drawImmersionChart() {{
  const canvas = document.getElementById('immersion-canvas');
  const empty = document.getElementById('immersion-chart-empty');
  const tip = document.getElementById('immersion-chart-tip');
  if (!canvas) return;
  const fold = document.getElementById('immersion-chart-fold');
  if (fold && !fold.open) return;

  const data = chartState.data;
  const year = (data && data.year) || new Date().getFullYear();
  const {{ dates, cum }} = buildYearAxis(year, (data && data.days) || []);
  const active = CHART_SERIES.filter(s => chartState.enabled[s.key] !== false);
  const hasAny = active.some(s => (cum[s.key] || []).some(v => v > 0));

  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.parentElement.getBoundingClientRect();
  const W = Math.max(280, rect.width);
  const H = Math.max(200, rect.height);
  canvas.width = W * dpr;
  canvas.height = H * dpr;
  canvas.style.width = W + 'px';
  canvas.style.height = H + 'px';
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = '#fffdf7';
  ctx.fillRect(0, 0, W, H);

  if (!hasAny) {{
    if (empty) empty.classList.add('show');
    canvas._plot = null;
    if (tip) tip.style.display = 'none';
    return;
  }}
  if (empty) empty.classList.remove('show');

  const pad = {{ t: 14, r: 16, b: 32, l: 44 }};
  const plotW = W - pad.l - pad.r;
  const plotH = H - pad.t - pad.b;

  // Each series is drawn on its own 0→max scale so hours/chars/pages can share one graph.
  const seriesDrawn = active.map(s => {{
    const vals = cum[s.key] || dates.map(() => 0);
    const max = Math.max(...vals, 0);
    return {{ ...s, vals, max }};
  }}).filter(s => s.max > 0);

  const xAt = (i) => pad.l + (i / Math.max(dates.length - 1, 1)) * plotW;
  const yAt = (v, max) => pad.t + plotH - (max > 0 ? (v / max) * plotH : 0);

  // grid
  ctx.strokeStyle = 'rgba(180,168,140,0.35)';
  ctx.lineWidth = 1;
  ctx.font = '600 10px IBM Plex Mono, monospace';
  ctx.fillStyle = '#6f6759';
  ctx.textAlign = 'right';
  for (let g = 0; g <= 4; g++) {{
    const y = pad.t + plotH - (plotH / 4) * g;
    ctx.beginPath();
    ctx.moveTo(pad.l, y);
    ctx.lineTo(pad.l + plotW, y);
    ctx.stroke();
    ctx.fillText((g * 25) + '%', pad.l - 6, y + 3);
  }}

  // x labels (month ticks)
  ctx.textAlign = 'center';
  let lastMonth = '';
  dates.forEach((d, i) => {{
    const m = d.slice(5, 7);
    if (m === lastMonth && i !== dates.length - 1) return;
    // first of month or last point
    if (d.slice(8, 10) !== '01' && i !== 0 && i !== dates.length - 1) return;
    lastMonth = m;
    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    ctx.fillText(months[parseInt(m, 10) - 1] || d.slice(5), xAt(i), H - 10);
  }});

  // axes
  ctx.strokeStyle = '#1a1712';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(pad.l, pad.t);
  ctx.lineTo(pad.l, pad.t + plotH);
  ctx.lineTo(pad.l + plotW, pad.t + plotH);
  ctx.stroke();

  // lines
  seriesDrawn.forEach((s) => {{
    ctx.strokeStyle = s.color;
    ctx.lineWidth = 2.2;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.globalAlpha = 0.92;
    ctx.beginPath();
    s.vals.forEach((v, i) => {{
      const x = xAt(i), y = yAt(v, s.max);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }});
    ctx.stroke();
    // end dot + label
    const last = s.vals[s.vals.length - 1] || 0;
    const x = xAt(s.vals.length - 1);
    const y = yAt(last, s.max);
    ctx.globalAlpha = 1;
    ctx.fillStyle = s.color;
    ctx.beginPath();
    ctx.arc(x, y, 3.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.font = '700 11px IBM Plex Sans, system-ui, sans-serif';
    ctx.textAlign = 'right';
    ctx.fillText(s.fmt(last), Math.max(pad.l + 8, x - 8), Math.max(pad.t + 12, y - 8));
  }});
  ctx.globalAlpha = 1;

  canvas._plot = {{ pad, plotW, plotH, dates, seriesDrawn, W, H, xAt, yAt }};
}}

function bindImmersionChartHover() {{
  const canvas = document.getElementById('immersion-canvas');
  const tip = document.getElementById('immersion-chart-tip');
  if (!canvas || !tip || canvas._bound) return;
  canvas._bound = true;
  canvas.addEventListener('mousemove', (ev) => {{
    const plot = canvas._plot;
    if (!plot || !plot.seriesDrawn.length) {{ tip.style.display = 'none'; return; }}
    const rect = canvas.getBoundingClientRect();
    const x = ev.clientX - rect.left;
    const {{ pad, plotW, dates, seriesDrawn, xAt }} = plot;
    if (x < pad.l || x > pad.l + plotW) {{ tip.style.display = 'none'; return; }}
    const t = (x - pad.l) / Math.max(plotW, 1);
    const i = Math.round(t * Math.max(dates.length - 1, 1));
    const idx = Math.max(0, Math.min(dates.length - 1, i));
    const d = dates[idx];
    const rows = seriesDrawn.map(s => {{
      const v = s.vals[idx] || 0;
      return `<div class="row"><span class="dot" style="background:${{s.color}}"></span>${{s.label}}: ${{s.fmt(v)}}</div>`;
    }}).join('');
    tip.innerHTML = `<strong>${{d}}</strong>${{rows}}`;
    tip.style.display = 'block';
    const tipW = tip.offsetWidth || 160;
    const tipH = tip.offsetHeight || 60;
    let left = x + 12;
    let top = (ev.clientY - rect.top) - tipH - 8;
    if (left + tipW > rect.width - 4) left = x - tipW - 12;
    if (top < 4) top = (ev.clientY - rect.top) + 14;
    tip.style.left = left + 'px';
    tip.style.top = top + 'px';

    // vertical guide
    drawImmersionChart();
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const gx = xAt(idx);
    ctx.strokeStyle = 'rgba(28,25,20,0.25)';
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 3]);
    ctx.beginPath();
    ctx.moveTo(gx, plot.pad.t);
    ctx.lineTo(gx, plot.pad.t + plot.plotH);
    ctx.stroke();
    ctx.setLineDash([]);
  }});
  canvas.addEventListener('mouseleave', () => {{
    tip.style.display = 'none';
    drawImmersionChart();
  }});
}}

async function refreshImmersionVisuals(force) {{
  const chartFold = document.getElementById('immersion-chart-fold');
  const heatFold = document.getElementById('immersion-heat-fold');
  const needData = (chartFold && chartFold.open) || (heatFold && heatFold.open);
  if (!needData && !force) return;
  await ensureTimeline(!!force);
  if (!chartFold || chartFold.open) drawImmersionChart();
  if (!heatFold || heatFold.open) drawImmersionHeatmap();
}}

loadChartPrefs();
renderSeriesChips();
renderHeatMetricChips();
bindImmersionChartHover();
refreshMetrics();
refreshImmersionVisuals(true);
setInterval(() => {{ refreshMetrics(); refreshImmersionVisuals(true); }}, 30000);
window.addEventListener('resize', () => {{
  if (chartState.data) {{
    drawImmersionChart();
    drawImmersionHeatmap();
  }}
}});
</script>
"""
    return _shell("Immersion Tracker", body, active="home")


def queue_page() -> str:
    """Unified Inbox: media queue + GSM + Hoshi reading + recent."""
    urls = _tool_urls()
    body = f"""
<main id="main" class="page page-wide page-inbox" tabindex="-1">
  <div class="mast">
    <h1>Inbox</h1>
    <div class="meta">
      <span class="count-badge zero" id="q-count">0</span>
      <span id="q-sub">loading…</span>
      · Media · GSM · ABS · Reading → Tadoku ·
      <a href="/logs">Logs</a> ·
      <a href="/">Dashboard</a>
    </div>
  </div>
  <details class="help-fold inbox-how">
    <summary>How this page works</summary>
    <div class="help-body">
      <p class="inbox-lede" style="margin:0">
        <b>1.</b> Approve or skip media ·
        <b>2.</b> Submit ready ·
        <b>3.</b> Log GSM / ABS / Reading gaps.
        Status &amp; Mode live under each row’s <b>Edit</b>.
      </p>
    </div>
  </details>
  {_queue_chrome(urls, mode="page", full_page_link=True)}
  {_gsm_fold_html(default_open=False)}
  {_abs_fold_html(default_open=False)}
  {reading_fold_html(default_open=False)}
  {_recent_logs_fold_html(default_open=False)}
</main>
<script>
{QUEUE_JS}
{READING_JS}
loadSettings();
loadQueue();
loadRecentLogs();
bindGsmPanel();
if (typeof bindAbsPanel === 'function') bindAbsPanel();
if (typeof bindReadingPanel === 'function') bindReadingPanel();
setInterval(() => {{
  loadQueue();
  loadRecentLogs();
  if (typeof loadGsmPanel === 'function') loadGsmPanel();
  if (typeof loadAbsPanel === 'function') loadAbsPanel();
  if (typeof loadReading === 'function') loadReading();
}}, 15000);
</script>
"""
    return _shell(
        "Inbox · Immersion Tracker",
        body,
        active="queue",
        extra_css=READING_CSS,
    )


def logs_page() -> str:
    """Full logs browser: sort, filter, edit, create."""
    urls = _tool_urls()
    return _logs_page_html(
        tautulli=urls["tautulli"],
        tadoku=urls["tadoku"],
        sheets=urls["sheets"],
        plex=urls["plex"],
    )


def reading_page() -> str:
    """Hoshi reading buckets: pending chars per book, session fragments, submit."""
    return _reading_page_html()


def progress_page() -> str:
    """Per-work progress: list/grid, category filters, Tadoku pull, jiten cache."""
    urls = _tool_urls()
    return _progress_page_html(
        tautulli=urls["tautulli"],
        tadoku=urls["tadoku"],
        sheets=urls["sheets"],
        plex=urls["plex"],
        contest_url=urls["tadoku_club"],
    )


def catalog_page() -> str:
    urls = _tool_urls()
    sheets_link = ""
    if urls["sheets"]:
        sheets_link = (
            f'<a href="{escape(urls["sheets"])}" target="_blank" rel="noopener">'
            f"Sheets · Catalog</a> · "
        )
    body = f"""
<main id="main" class="page page-catalog" tabindex="-1">
  <div class="mast">
    <h1>Catalog / aliases</h1>
    <div class="meta">
      {sheets_link}
      <a href="{escape(urls['tautulli'])}" target="_blank" rel="noopener">Tautulli</a>
      · <a href="{escape(urls['plex'])}" target="_blank" rel="noopener">Plex</a>
      · <a href="/logs">Logs</a>
      · <a href="/queue">Queue</a>
    </div>
  </div>

  <div class="how-card">
    <h2>How this works</h2>
    <ol class="how-steps">
      <li><b>Plex</b> sends the library show title (often English).</li>
      <li>Put that exact title in <b>aliases</b> so it maps to your <b>series_key</b>.</li>
      <li>Logs use your <b>display title</b> (e.g. JP name) in queue, sheet, and Tadoku.</li>
      <li><b>Tadoku mode</b> on the catalog row applies to <i>new</i> logs, and to past logs when you <b>Relink</b>.</li>
    </ol>
    <p class="faint" style="margin:0.55rem 0 0">
      Example: alias <code>KONOSUBA - God's blessing…</code>
      → display <code>この素晴らしい世界に祝福を</code>
      · key <code>anime:konosuba</code>
    </p>
  </div>

  <div class="card-form">
    <h2 class="card-h">Link a Plex title → series</h2>
    <p class="field-hint" style="margin-top:0">
      Create or update a catalog row, attach the Plex show name as an alias, and optionally rewrite existing logs.
    </p>
    <div class="row">
      <div>
        <label for="lk_key">series_key</label>
        <input id="lk_key" placeholder="anime:konosuba" autocomplete="off"/>
        <p class="field-hint">Stable id shared with manual entry. Prefer short keys: <code>anime:…</code></p>
      </div>
      <div>
        <label for="lk_title">Display title</label>
        <input id="lk_title" placeholder="この素晴らしい世界に祝福を" autocomplete="off"/>
        <p class="field-hint">How the work appears on logs / queue / Tadoku (not the episode title).</p>
      </div>
    </div>
    <div class="row">
      <div>
        <label for="lk_type">Content type</label>
        <select id="lk_type">
          <option value="anime">anime</option>
          <option value="show">show</option>
          <option value="movie">movie</option>
          <option value="youtube">youtube</option>
          <option value="book">book</option>
          <option value="manga">manga</option>
          <option value="visual_novel">visual_novel</option>
        </select>
      </div>
      <div>
        <label for="lk_tadoku">Tadoku mode (catalog override)</label>
        <select id="lk_tadoku">
          <option value="">— inherit type default —</option>
          <option value="auto">auto — submit without approve</option>
          <option value="pending">pending — approve first</option>
          <option value="never">never — skip Tadoku</option>
        </select>
        <p class="field-hint">Applied on new logs; also on past pipeline logs when you relink.</p>
      </div>
    </div>
    <div class="row">
      <div>
        <label for="lk_alias">Plex title alias</label>
        <input id="lk_alias" placeholder="KONOSUBA - God's blessing on this wonderful world!" autocomplete="off"/>
        <p class="field-hint">Exact show name from Plex / Tautulli (case-insensitive). Copy from a log if unsure.</p>
      </div>
      <div>
        <label for="lk_aliases">Extra aliases <span class="faint">(optional)</span></label>
        <input id="lk_aliases" placeholder="KonoSuba | このすば" autocomplete="off"/>
        <p class="field-hint">Pipe-separated: <code>Name A | Name B</code></p>
      </div>
    </div>
    <div class="form-actions">
      <label class="check-label">
        <input type="checkbox" id="lk_relink" checked/>
        Relink matching past logs (title, series_key, tadoku mode)
      </label>
      <div class="btn-row">
        <button type="button" class="process" onclick="linkAlias()">Save link</button>
        <button type="button" class="secondary" onclick="clearLinkForm()">Clear</button>
      </div>
    </div>
    <div id="msg" class="form-msg" role="status"></div>
  </div>

  <div class="card-form">
    <div class="catalog-list-head">
      <div>
        <h2 class="card-h" style="margin:0">All catalog rows</h2>
        <p class="field-hint" style="margin:0.25rem 0 0">
          Click column headers to sort.
          <b>Save</b> writes the row (SQLite + Sheets).
          <b>Relink</b> rewrites matching past logs (title / key / tadoku override).
          Does not reopen <code>pushed</code> or user <code>skipped</code> logs.
        </p>
      </div>
      <div class="catalog-filter-wrap">
        <label for="cat_filter">Filter</label>
        <input id="cat_filter" placeholder="Search key, title, alias…" oninput="filterCatalog()" autocomplete="off"/>
      </div>
    </div>
    <div id="list"></div>
  </div>
</main>
<script>
const CAT_TYPES=['anime','show','movie','youtube','book','manga','visual_novel','game','podcast','study'];
const CAT_UNITS=['','minutes','minutes_high_density','pages','two_column_pages','comic_pages','characters','sentences'];
let _catalogCache = [];
let _catSort = {{ key: 'series_key', dir: 'asc' }};
function escapeHtml(s){{return String(s??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));}}
function msg(t, kind){{
  const el=document.getElementById('msg');
  el.textContent=t||'';
  el.className='form-msg'+(kind?(' '+kind):'');
}}
function tadokuSelect(key, selected){{
  const opts=[
    ['','inherit'],
    ['auto','auto'],
    ['pending','pending'],
    ['never','never'],
  ];
  const sel=selected||'';
  return `<select data-k="${{escapeHtml(key)}}" data-f="tadoku_override">`+
    opts.map(([v,l])=>`<option value="${{v}}"${{v===sel?' selected':''}}>${{l}}</option>`).join('')+
    `</select>`;
}}
function typeSelect(key, selected){{
  const sel=selected||'anime';
  return `<select data-k="${{escapeHtml(key)}}" data-f="content_type">`+
    CAT_TYPES.map(v=>`<option value="${{v}}"${{v===sel?' selected':''}}>${{v}}</option>`).join('')+
    `</select>`;
}}
function unitSelect(key, selected){{
  const sel=selected||'';
  return `<select data-k="${{escapeHtml(key)}}" data-f="default_unit">`+
    CAT_UNITS.map(v=>`<option value="${{v}}"${{v===sel?' selected':''}}>${{v||'— default —'}}</option>`).join('')+
    `</select>`;
}}
function filteredRows(data){{
  const q=(document.getElementById('cat_filter').value||'').trim().toLowerCase();
  let rows=q?data.filter(c=>{{
    const blob=[c.series_key,c.display_title,c.content_type,c.aliases,c.tadoku_override,c.notes,c.default_unit].join(' ').toLowerCase();
    return blob.includes(q);
  }}):data.slice();
  const k=_catSort.key, dir=_catSort.dir==='asc'?1:-1;
  rows.sort((a,b)=>{{
    const va=(a[k]==null?'':String(a[k])).toLowerCase();
    const vb=(b[k]==null?'':String(b[k])).toLowerCase();
    const c=va.localeCompare(vb);
    return c===0?String(a.series_key).localeCompare(String(b.series_key)):c*dir;
  }});
  return rows;
}}
function sortInd(key){{
  if(_catSort.key!==key) return '';
  return `<span class="sort-ind">${{_catSort.dir==='asc'?'▲':'▼'}}</span>`;
}}
function thSort(key, label){{
  const on=_catSort.key===key?' sorted':'';
  return `<th data-sort="${{key}}" class="${{on.trim()}}" onclick="toggleCatSort('${{key}}')">${{label}}${{sortInd(key)}}</th>`;
}}
function toggleCatSort(key){{
  if(_catSort.key===key) _catSort.dir=_catSort.dir==='asc'?'desc':'asc';
  else {{ _catSort.key=key; _catSort.dir='asc'; }}
  renderList(_catalogCache);
}}
function renderList(data){{
  const root=document.getElementById('list');
  const rows=filteredRows(data);
  if(!data.length){{
    root.innerHTML='<p class="empty-q">No catalog rows yet. Link a title above, or log something so a row is auto-created.</p>';
    return;
  }}
  if(!rows.length){{
    root.innerHTML='<p class="empty-q">No rows match that filter.</p>';
    return;
  }}
  let html=`<div class="catalog-table-wrap"><table class="catalog-table data-table"><thead><tr>
    ${{thSort('series_key','series_key')}}
    ${{thSort('display_title','Display title')}}
    ${{thSort('content_type','Type')}}
    ${{thSort('tadoku_override','Tadoku')}}
    ${{thSort('default_unit','Unit')}}
    ${{thSort('aliases','Aliases (Plex names)')}}
    <th>Notes</th>
    <th></th>
  </tr></thead><tbody>`;
  for(const c of rows){{
    const id=escapeHtml(c.series_key);
    const rawKey=JSON.stringify(c.series_key);
    html+=`<tr data-row-key="${{id}}">
      <td class="col-key"><code title="${{id}}">${{id}}</code></td>
      <td class="col-title"><input data-k="${{id}}" data-f="display_title" value="${{escapeHtml(c.display_title||'')}}" aria-label="display title for ${{id}}"/></td>
      <td class="col-type">${{typeSelect(c.series_key, c.content_type||'anime')}}</td>
      <td class="col-tadoku">${{tadokuSelect(c.series_key, c.tadoku_override||'')}}</td>
      <td class="col-unit">${{unitSelect(c.series_key, c.default_unit||'')}}</td>
      <td class="col-aliases"><input data-k="${{id}}" data-f="aliases" value="${{escapeHtml(c.aliases||'')}}" placeholder="Plex Name | Other" aria-label="aliases for ${{id}}"/></td>
      <td class="col-notes"><input data-k="${{id}}" data-f="notes" value="${{escapeHtml(c.notes||'')}}" placeholder="—" aria-label="notes for ${{id}}"/></td>
      <td class="col-actions">
        <button type="button" class="secondary" title="Save row to DB / Sheets" onclick='saveRow(${{rawKey}})'>Save</button>
        <button type="button" class="process" title="Rewrite matching past logs" onclick='relink(${{rawKey}})'>Relink</button>
      </td>
    </tr>`;
  }}
  html+='</tbody></table></div>';
  root.innerHTML=html;
}}
function filterCatalog(){{ renderList(_catalogCache); }}
async function load(){{
  try{{
    const data=await (await fetch('/api/catalog')).json();
    _catalogCache=Array.isArray(data)?data:[];
    renderList(_catalogCache);
  }}catch(e){{
    document.getElementById('list').innerHTML='<p class="form-msg err">Failed to load catalog.</p>';
  }}
}}
function field(key,f){{
  const nodes=[...document.querySelectorAll('[data-k][data-f]')];
  const el=nodes.find(e=>e.dataset.k===key&&e.dataset.f===f);
  return el?el.value:'';
}}
function clearLinkForm(){{
  ['lk_key','lk_title','lk_alias','lk_aliases'].forEach(id=>{{document.getElementById(id).value='';}});
  document.getElementById('lk_type').value='anime';
  document.getElementById('lk_tadoku').value='';
  document.getElementById('lk_relink').checked=true;
  msg('');
}}
function rowBody(key){{
  return {{
    display_title:field(key,'display_title'),
    content_type:field(key,'content_type')||undefined,
    aliases:field(key,'aliases')||null,
    tadoku_override:field(key,'tadoku_override')||null,
    default_unit:field(key,'default_unit')||null,
    notes:field(key,'notes')||null,
  }};
}}
async function saveRow(key){{
  const body=rowBody(key);
  const r=await fetch('/api/catalog/'+encodeURIComponent(key)+'?relink_logs=false',{{
    method:'PATCH',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}});
  if(r.ok){{
    msg(`Saved ${{key}} (row only — use Relink to update past logs)`, 'ok');
    load();
  }}else{{
    msg(await r.text(), 'err');
  }}
}}
async function relink(key){{
  const body=rowBody(key);
  const save=await fetch('/api/catalog/'+encodeURIComponent(key)+'?relink_logs=false',{{
    method:'PATCH',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}});
  if(!save.ok){{msg(await save.text(),'err');return;}}
  const r=await fetch('/api/catalog/'+encodeURIComponent(key)+'/relink',{{method:'POST'}});
  const j=await r.json().catch(()=>({{}}));
  if(r.ok){{
    const n=j.updated||0;
    const t=j.tadoku_updated||0;
    msg(`Relinked ${{key}}: ${{n}} log(s) updated`+(t?` · tadoku mode on ${{t}}`:'')+' (pushed/skipped left alone)', 'ok');
    load();
  }}else{{
    msg(JSON.stringify(j),'err');
  }}
}}
async function linkAlias(){{
  const body={{
    series_key:document.getElementById('lk_key').value.trim(),
    display_title:document.getElementById('lk_title').value.trim(),
    content_type:document.getElementById('lk_type').value,
    alias:document.getElementById('lk_alias').value.trim()||null,
    aliases:document.getElementById('lk_aliases').value.trim()||null,
    tadoku_override:document.getElementById('lk_tadoku').value||null,
    relink_logs:document.getElementById('lk_relink').checked,
  }};
  if(!body.series_key||!body.display_title){{msg('series_key and display title are required','err');return;}}
  if(!body.alias&&!body.aliases){{msg('Add at least one Plex title alias (or extra aliases)','err');return;}}
  const r=await fetch('/api/catalog/link',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}});
  const j=await r.json().catch(()=>({{}}));
  if(r.ok){{
    const rel=j.relink||{{}};
    const parts=[
      j.created?'created':'updated',
      body.relink_logs?`${{rel.updated||0}} log(s) relinked`:'no relink',
    ];
    if(rel.tadoku_updated) parts.push(`tadoku on ${{rel.tadoku_updated}}`);
    msg(`Linked ${{body.series_key}} (${{parts.join(' · ')}})`, 'ok');
    load();
  }}else{{
    msg(typeof j==='object'?JSON.stringify(j):String(j),'err');
  }}
}}
load();
</script>
"""
    return _shell("Catalog · Immersion Tracker", body, active="catalog")


def race_page() -> str:
    """Contest momentum — scoreboard-first race board."""
    urls = _tool_urls()
    contest_name = escape(urls["contest_name"]) if urls["contest_name"] else "Contest"
    me_user = ""
    try:
        from app.tadoku.credentials import saved_username

        me_user = (saved_username() or "").strip()
    except Exception:
        me_user = ""
    me_js = (
        me_user.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("<", "")
        .replace(">", "")
    )
    body = f"""
<main id="main" class="page page-wide page-race" tabindex="-1">
  <div id="race-error" class="race-error" style="display:none"></div>

  <div class="race-stamp">
    <div class="race-stamp-top">
      <div>
        <p class="race-stamp-kicker">Race</p>
        <h1 id="race-title">{contest_name}</h1>
        <p class="race-sub" id="race-sub">Loading contest…</p>
      </div>
      <div class="race-actions">
        <button type="button" class="primary btn-refresh" id="btn-refresh">Refresh</button>
        <span class="cache-meta" id="cache-meta">…</span>
        <a class="quiet" href="{escape(urls['tadoku_contest'])}" target="_blank" rel="noopener">tadoku ↗</a>
      </div>
    </div>
    <div class="race-stamp-meta" id="race-stamp-meta">
      <span><b id="stat-days">—</b> days left</span>
      <span><b id="stat-runners">—</b> runners</span>
      <span>as of <b id="stat-asof">—</b></span>
      <span id="race-pulse-line">—</span>
    </div>
  </div>

  <div id="race-loading" class="race-loading race-skeleton" aria-live="polite">
    <div class="sk-row"></div><div class="sk-row"></div><div class="sk-row"></div>
    <div class="sk-row"></div><div class="sk-row"></div>
    <p class="sk-label"><span class="spin"></span>Building scoreboard…</p>
  </div>

  <div id="race-main" style="display:none">
    <section class="race-scoreboard" aria-label="Top of the board">
      <div class="race-scoreboard-head">
        <h2>Scoreboard</h2>
        <span class="hint" id="scoreboard-hint">Top 5 · click a row to highlight on chart</span>
      </div>
      <div class="race-you-line" id="race-you-line" hidden></div>
      <div id="race-scoreboard" class="race-scoreboard-body"></div>
    </section>

    <div class="band-grid band-grid-compact">
      <section class="band heating">
        <div class="band-head">
          <h2>Heating up</h2>
          <span class="hint">Faster last 7d than 30d</span>
        </div>
        <div class="band-body" id="band-heating"></div>
      </section>
      <section class="band catching">
        <div class="band-head">
          <h2>Catching up</h2>
          <span class="hint">Days to pass rank above</span>
        </div>
        <div class="band-body" id="band-catching"></div>
      </section>
      <section class="band cooling">
        <div class="band-head">
          <h2>Cooling / idle</h2>
          <span class="hint">Slower pace or idle</span>
        </div>
        <div class="band-body" id="band-cooling"></div>
      </section>
    </div>

    <details class="race-panel-fold" id="race-project-fold">
      <summary>Project the race <span class="hint">pace → future places</span></summary>
      <div class="fold-inner">
        <section class="project-panel" aria-label="Pace projection" style="border:0;margin:0">
          <div class="project-toolbar">
            <h2>Project the race</h2>
            <label>Horizon
              <select id="proj-horizon" title="How far to project at current pace">
                <option value="7">+7 days</option>
                <option value="14">+14 days</option>
                <option value="30" selected>+30 days</option>
                <option value="60">+60 days</option>
                <option value="90">+90 days</option>
                <option value="end">Contest end</option>
                <option value="custom">Custom…</option>
              </select>
            </label>
            <label style="display:none" id="proj-custom-wrap">Days
              <input type="number" id="proj-custom-days" min="0" max="400" step="1" value="30"/>
            </label>
            <label>Pace model
              <select id="proj-model">
                <option value="velocity" selected>7-day pace</option>
                <option value="baseline">30-day pace</option>
                <option value="accel">Accel trend</option>
              </select>
            </label>
            <span class="proj-summary" id="proj-summary">…</span>
          </div>
          <div class="project-body">
            <div class="project-podium">
              <p class="podium-head">Projected top 5</p>
              <div id="proj-podium"></div>
            </div>
            <div class="project-movers">
              <p class="podium-head">Biggest place movers</p>
              <div id="proj-movers"></div>
            </div>
          </div>
        </section>
      </div>
    </details>

    <details class="race-panel-fold" id="race-chart-fold">
      <summary>Point growth <span class="hint">solid = history · dashed = projected</span></summary>
      <div class="fold-inner">
        <section class="chart-panel" style="border:0;margin:0">
          <div class="chart-toolbar">
            <label>Show
              <select id="chart-mode">
                <option value="top5" selected>Top 5</option>
                <option value="top12">Top 12</option>
                <option value="heating">Heating pack</option>
                <option value="all">Everyone with points</option>
              </select>
            </label>
            <span class="spacer"></span>
            <span class="hint" style="font-size:0.75rem;color:var(--muted);font-weight:600">Click legend chips to toggle</span>
          </div>
          <div class="chart-wrap">
            <canvas id="race-canvas" aria-label="Cumulative score chart with projection"></canvas>
            <div class="chart-tip" id="chart-tip"></div>
          </div>
          <div class="chart-legend" id="chart-legend"></div>
        </section>
      </div>
    </details>

    <details class="race-panel-fold" id="race-table-fold">
      <summary>Standings <span class="hint">filter &amp; sort</span></summary>
      <div class="fold-inner">
        <section class="table-panel" style="border:0;margin:0">
          <div class="table-toolbar">
            <input type="search" id="race-search" placeholder="Filter runners…" autocomplete="off"/>
          </div>
          <div class="table-scroll">
            <table class="race-table">
              <thead>
                <tr>
                  <th data-sort="rank" title="Current rank">Now #</th>
                  <th class="proj-col" data-sort="projected_rank" id="th-proj-rank" title="Projected rank">Proj place</th>
                  <th class="proj-col" data-sort="rank_delta" id="th-rank-delta" title="Place change">Place Δ</th>
                  <th data-sort="display_name">Runner</th>
                  <th data-sort="score">Score now</th>
                  <th class="proj-col" data-sort="projected_score" id="th-proj-score">Score then</th>
                  <th data-sort="velocity_7d">7d pace</th>
                  <th data-sort="velocity_30d">30d pace</th>
                  <th data-sort="acceleration">Accel</th>
                  <th data-sort="momentum">Band</th>
                  <th data-sort="gap_above">Gap to ↑</th>
                  <th data-sort="days_to_catch">Catch-up</th>
                  <th>28d spark</th>
                </tr>
              </thead>
              <tbody id="race-tbody"></tbody>
            </table>
          </div>
        </section>
      </div>
    </details>

    <details class="help-fold">
      <summary>How to read this board</summary>
      <div class="help-body">
        <p class="faint" style="margin:0">
          <b>Scoreboard</b> = top 5 by score (bars relative to #1).
          <b>Heating</b> = 7d pace faster than 30d.
          <b>Catching</b> = days to pass rank above at current paces.
          <b>Accel</b> = 7d − 30d pace (pts/day).
          Cache TTL 15 min · force Refresh anytime.
        </p>
      </div>
    </details>
  </div>
</main>
<script>
window.RACE_ME = {{ username: '{me_js}' }};
{MOMENTUM_JS}
</script>
"""
    return _shell(
        "Contest Race · Immersion Tracker",
        body,
        active="race",
        extra_css=MOMENTUM_CSS,
    )

