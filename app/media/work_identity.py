"""
Canonical work identity for the Progress library shelf.

Goals:
  - One shelf row per *work* (One Piece), never per volume/log line
  - Study tools (Anki, Bunpro, Italki) never appear as anime/works
  - Contest carry-overs / pure numbers / bonus-point rows stay off the shelf
  - Ingest + aggregation share the same rules so issues don't come back
"""

from __future__ import annotations

import re
from typing import Any, Optional

from app.media.catalog_resolve import normalize_title
from app.media.title_format import slugify_series, suggest_series_key
from app.media.title_search import clean_search_title, identity_compact

# Tools / study platforms that are not immersion *works*
_STUDY_TOOL_RE = re.compile(
    r"^(?:"
    r"anki|bunpro|italki|wanikani|kitsun(?:e)?|jpdb|ankiweb|"
    r"r(?:enshuu)|migaku|language\s*reactor|fluentu|hellotalk|"
    r"duolingo|lingodeer|satori\s*reader|tadoku\s*app"
    r")\b",
    re.I,
)
_STUDY_SOURCES = frozenset({"anki"})

# Not a real media work (contest accounting, garbage keys)
_NON_WORK_RE = re.compile(
    r"(?:"
    r"carry[\s-]?over|challenge\s+bonus|weeb\s+club|manga\s+club|"
    r"^club\b|bonus\s+points?"
    r")",
    re.I,
)

# Known slug / nickname → stable display title (and key base)
_CANON_DISPLAY: dict[str, str] = {
    "aot": "Attack on Titan",
    "snk": "Attack on Titan",
    "bookworm": "Ascendance of a Bookworm",
    "gashiakuta": "Gachiakuta",
    "gachiakuta": "Gachiakuta",
    "yanineko": "ヤニねこ",
    "yani neko": "ヤニねこ",
    "mahoyo": "魔法使いの夜",
    "demonbane": "Demonbane",
    "steins gate": "Steins;Gate",
    "steins;gate": "Steins;Gate",
    "steinsgate": "Steins;Gate",
    "re zero": "Re:Zero",
    "re:zero": "Re:Zero",
    "rezero": "Re:Zero",
    "one piece": "One Piece",
    "one piece red": "ONE PIECE FILM RED",
    "one piece film red": "ONE PIECE FILM RED",
    "one piece film: red": "ONE PIECE FILM RED",
    "onepiecered": "ONE PIECE FILM RED",
    "ワンピース フィルム レッド": "ONE PIECE FILM RED",
    "dandadan": "ダンダダン",
    "dbz": "Dragon Ball Z",
    "db daima": "Dragon Ball Daima",
    "daima": "Dragon Ball Daima",
    "vineland saga": "Vinland Saga",
    "vinland saga": "Vinland Saga",
    "hajime no ippo": "Hajime no Ippo",
    "はじめの一歩": "Hajime no Ippo",
    "made in abyss": "Made in Abyss",
    "nhk": "Welcome to the NHK",
    "welcome to the nhk": "Welcome to the NHK",
    "welcome to the n h k": "Welcome to the NHK",
    "welcome to the n-h-k": "Welcome to the NHK",
    # Romaji / JP titles for the same show (Plex / AniList / manual logs)
    "nhk ni youkoso": "Welcome to the NHK",
    "nhk ni youkoso!": "Welcome to the NHK",
    "n h k ni youkoso": "Welcome to the NHK",
    "n.h.k. ni youkoso": "Welcome to the NHK",
    "n.h.k ni youkoso": "Welcome to the NHK",
    "n・h・kにようこそ": "Welcome to the NHK",
    "nhkにようこそ": "Welcome to the NHK",
    "eizouken": "Keep Your Hands Off Eizouken!",
    "ping pong the animation": "Ping Pong the Animation",
    "ping pong": "Ping Pong the Animation",
    "hyouka": "氷菓",
    "mushoku tensei": "無職転生",
    "無職転生": "無職転生",
    "yugi": "Yu-Gi-Oh!",
    "chi": "Chi's Sweet Home",
    "hogwards legacy": "Hogwarts Legacy",
    "hogwarts legacy": "Hogwarts Legacy",
    "first of the north star": "Fist of the North Star",
    "fist of the north star": "Fist of the North Star",
    "muramasa": "Muramasa",
    "tsukihime": "Tsukihime",
    "13 sentinels": "13 Sentinels: Aegis Rim",
    "trails in the sky fc": "Trails in the Sky",
    "trails in the sky": "Trails in the Sky",
    "wednesday downtown monster": "Wednesday Downtown",
    "wednesday downtown monster idol": "Wednesday Downtown",
    "wednesday downtown monster love": "Wednesday Downtown",
    "wednesday downtown monster house": "Wednesday Downtown",
    "wednesday downtown": "Wednesday Downtown",
    "konosuba": "この素晴らしい世界に祝福を！",
    "この素晴らしい世界に祝福を": "この素晴らしい世界に祝福を！",
    "この素晴らしい世界に祝福を！": "この素晴らしい世界に祝福を！",
    "solo leveling": "俺だけレベルアップな件",
    "dr stone": "Dr. STONE",
    "psycho pass": "Psycho-Pass",
    "golden kamuy": "Golden Kamuy",
    "yowamushi pedal": "Yowamushi Pedal",
    "gto": "GTO",
    # Manga shelf identities
    "mad": "MAD",
    "mad chapter": "MAD",
    "mad ch": "MAD",
    "とつくにの少女": "とつくにの少女",
    "totsukuni no shoujo": "とつくにの少女",
    "the girl from the other side": "とつくにの少女",
    "arcane": "Arcane",
}

# Known work → forced content_type (fixes log type drift / wrong prefix)
_KNOWN_CONTENT_TYPES: dict[str, str] = {
    "mad": "manga",
    "とつくにの少女": "manga",
    "totsukuni no shoujo": "manga",
    "the girl from the other side": "manga",
    "hogwarts legacy": "game",
    "hogwards legacy": "game",
    "arcane": "show",
    "hajime no ippo": "anime",
    "はじめの一歩": "anime",
    # Movies / theatrical films (must not resolve as the long-running TV anime)
    "one piece red": "movie",
    "one piece film red": "movie",
    "one piece film: red": "movie",
    "onepiecered": "movie",
    "ワンピース フィルム レッド": "movie",
}

# Theatrical / film title cues — force content_type=movie when unambiguous
_MOVIE_TITLE_RE = re.compile(
    r"(?:"
    r"\bfilm\s*[:\-]?\s*red\b|"
    r"\bone\s*piece\s+red\b|"
    r"\bfilm\b|"
    r"\bthe\s+movie\b|"
    r"\bmovie\b|"
    r"映画"
    r")",
    re.I,
)

# series_key slug aliases → preferred slug suffix (after type prefix)
_KEY_SLUG_ALIASES: dict[str, str] = {
    "gashiakuta": "gachiakuta",
    "attack-on-titan-e1-e17": "attack-on-titan",
    "aot": "attack-on-titan",
    "re-zero-s01e01-double": "re-zero",
    "re-zero-se1e02": "re-zero",
    "mahoyo-double": "mahoyo",
    "one-piece-18-224-pages": "one-piece",
    "one-piece-19-218-pages": "one-piece",
    "one-piece-20-218-pages": "one-piece",
    "one-piece-31-half": "one-piece",
    "one-piece-34-half-correcting-old-log-description": "one-piece",
    "one-piece-vol": "one-piece",
    "one-piece-volume": "one-piece",
    "one-piece-vol-10-half-credit": "one-piece",
    "one-piece-vol-11-page": "one-piece",
    "one-piece-challenge-bonus-points": "one-piece",
    "onepiecered": "one-piece-film-red",
    "one-piece-red": "one-piece-film-red",
    "one-piece-film-red": "one-piece-film-red",
    "db-daima": "dragon-ball-daima",
    "dbz": "dragon-ball-z",
    "dbz-4": "dragon-ball-z",
    "arcane-s1-s2": "arcane",
    "arcane-s1-s2-740min-half": "arcane",
    "hajime-no-ippo-s1-s2": "hajime-no-ippo",
    "hajime-no-ippo-s1-s2-102-eps-half": "hajime-no-ippo",
    "vineland-saga-season": "vinland-saga",
    "made-in-abyss-vol-1-page-0-26": "made-in-abyss",
    "metaphor-refantazio-half": "metaphor-refantazio",
    "muramasa-half": "muramasa",
    "wednesday-downtown-monster": "wednesday-downtown",
    "wednesday-downtown-monster-idol": "wednesday-downtown",
    "wednesday-downtown-monster-love": "wednesday-downtown",
    "wednesday-downtown-monster-house": "wednesday-downtown",
    # Welcome to the NHK — all name forms → one shelf key
    "nhk": "welcome-to-the-nhk",
    "welcome-to-the-n-h-k": "welcome-to-the-nhk",
    "welcome-to-the-nhk": "welcome-to-the-nhk",
    "nhk-ni-youkoso": "welcome-to-the-nhk",
    "n-h-k-ni-youkoso": "welcome-to-the-nhk",
    "n-h-kにようこそ": "welcome-to-the-nhk",
    "nhkにようこそ": "welcome-to-the-nhk",
    "n-h-k": "welcome-to-the-nhk",
    "この素晴らしい世界に祝福を": "konosuba",
    "hogwards-legacy": "hogwarts-legacy",
    "hogwards-legacy-half": "hogwarts-legacy",
    "first-of-the-north-star": "fist-of-the-north-star",
    "chi-0-to": "chi",
    "mad-chapter": "mad",
    "mad-ch": "mad",
    "mad-1": "mad",
    "mad-2": "mad",
    "mad-3": "mad",
    "mad-ch-9": "mad",
    "mad-chapter-4-8": "mad",
    "とつくにの少女": "totsukuni-no-shoujo",
    "とつくにの少女-9-10": "totsukuni-no-shoujo",
    "totsukuni-no-shoujo": "totsukuni-no-shoujo",
    "the-girl-from-the-other-side": "totsukuni-no-shoujo",
    # NOTE: never map bare "vol" / "vol-1-page" → a franchise (was collapsing
    # unrelated volume fragments into Dandadan)
    "anki-4-9th": "anki",
    "anki-13th-to-26th": "anki",
    "anki-2nd-12th-15-min-avg": "anki",
    "anki-11-25-14min-missed-2-days": "anki",
}

_PAGE_PAREN = re.compile(
    r"\s*[\(（\[]\s*\d+\s*pages?[\)）\]]?\s*$",
    re.I,
)
_TRAILING_JUNK = re.compile(
    r"\s*(?:half|credit|correcting.*|description|from\s+switch).*$",
    re.I,
)

# ---------------------------------------------------------------------------
# Title identity: combine EN / JP / romaji names of the same work
# ---------------------------------------------------------------------------
# Built lazily from TITLE_ALIASES + _CANON_DISPLAY so Progress shelves one row
# for "Welcome to the NHK" / "NHK ni Youkoso!" / "N・H・Kにようこそ".

_IDENTITY_DISPLAY_BY_COMPACT: dict[str, str] = {}
_IDENTITY_SLUG_BY_SLUG: dict[str, str] = {}
_identity_index_ready = False


def _pick_cluster_display(
    names: list[str],
    *,
    preferred: Optional[str] = None,
) -> str:
    """
    Prefer an explicit _CANON_DISPLAY value, else curated TITLE_ALIASES head,
    else a solid English / CJK form.
    """
    for n in names:
        nt = normalize_title(n)
        if nt in _CANON_DISPLAY:
            return _CANON_DISPLAY[nt]
        for alias, display in _CANON_DISPLAY.items():
            if identity_compact(alias) == identity_compact(n):
                return display
            if identity_compact(display) == identity_compact(n):
                return display
    # First curated name from TITLE_ALIASES (lists are preference-ordered)
    if preferred and preferred.strip():
        return preferred.strip()
    # Prefer a multi-word Latin title over a short nickname key
    latin = [
        n
        for n in names
        if re.search(r"[A-Za-z]", n)
        and not re.search(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]", n)
        and " " in n.strip()
    ]
    if latin:
        latin.sort(key=lambda s: (-len(s.strip()), s.lower()))
        return latin[0].strip()
    latin_any = [
        n
        for n in names
        if re.search(r"[A-Za-z]", n)
        and not re.search(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]", n)
    ]
    if latin_any:
        # Prefer shorter common name (Frieren over Sousou no Frieren)
        latin_any.sort(key=lambda s: (len(s.strip()), s.lower()))
        return latin_any[0].strip()
    cjk = [
        n
        for n in names
        if re.search(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]", n)
    ]
    if cjk:
        cjk.sort(key=lambda s: (-len(s.strip()), s))
        return cjk[0].strip()
    return (names[0] if names else "").strip()


def _pick_cluster_slug(names: list[str], display: str) -> str:
    """One stable series_key suffix for every name in the cluster."""
    # 1) Existing explicit slug redirects win (nhk → welcome-to-the-nhk, …)
    for n in names + [display]:
        s = slugify_series(n)
        if s in _KEY_SLUG_ALIASES:
            return _KEY_SLUG_ALIASES[s]
    # 2) Latin reverse-alias of the preferred display (same as canonical_series_key)
    #    e.g. display "GTO" / "Welcome to the NHK" → nickname key "gto" / "nhk"
    nt = normalize_title(display)
    key_title = display
    for alias, d in _CANON_DISPLAY.items():
        if normalize_title(d) == nt and re.search(r"[A-Za-z]", alias):
            key_title = alias
            break
    preferred = slugify_series(key_title)
    if preferred in _KEY_SLUG_ALIASES:
        return _KEY_SLUG_ALIASES[preferred]
    # 3) Prefer a short nickname slug already among members (gto, frieren, aot)
    #    over a long official title slug — shelf keys stay stable.
    ascii_slugs = []
    for n in names + [display, key_title]:
        s = slugify_series(n)
        if s and re.fullmatch(r"[a-z0-9-]+", s) and len(s) >= 2:
            ascii_slugs.append(s)
    if preferred and preferred in ascii_slugs:
        return preferred
    if ascii_slugs:
        # Shortest stable Latin slug (gto, frieren) beats full official names
        return min(ascii_slugs, key=lambda s: (len(s), s))
    return preferred or slugify_series(display) or "unknown"


def _build_title_identity_index() -> None:
    """
    Union EN/JP/romaji names of the same work into one display + series_key slug.

    Sources:
      - TITLE_ALIASES clusters (metadata search nicknames)
      - _CANON_DISPLAY (Progress shelf nicknames)
      - _KEY_SLUG_ALIASES (existing key redirects)
    """
    global _identity_index_ready
    if _identity_index_ready:
        return

    from collections import defaultdict

    from app.media.title_search import TITLE_ALIASES

    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        if not a or not b:
            return
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    members: dict[str, list[str]] = defaultdict(list)
    # compact root → first curated TITLE_ALIASES head (preference-ordered)
    preferred_by_compact: dict[str, str] = {}

    def add_member(name: str) -> str:
        c = identity_compact(name)
        if not c:
            return ""
        find(c)
        members[c].append(name)
        return c

    for alias_key, names in TITLE_ALIASES.items():
        comps = [add_member(alias_key)]
        for n in names:
            comps.append(add_member(n))
        comps = [c for c in comps if c]
        for c in comps[1:]:
            union(comps[0], c)
        # Curated list head is the preferred shelf/search title
        if names:
            head = names[0].strip()
            if head:
                for c in comps:
                    root = find(c)
                    preferred_by_compact.setdefault(root, head)

    for alias, display in _CANON_DISPLAY.items():
        ca, cd = add_member(alias), add_member(display)
        if ca and cd:
            union(ca, cd)

    # Group original name strings by union root
    cluster: dict[str, list[str]] = defaultdict(list)
    seen_name: dict[str, set[str]] = defaultdict(set)
    for compact, names in members.items():
        root = find(compact)
        for n in names:
            nk = normalize_title(n)
            if nk and nk not in seen_name[root]:
                seen_name[root].add(nk)
                cluster[root].append(n)

    display_by_compact: dict[str, str] = {}
    slug_by_slug: dict[str, str] = {}

    for root, names in cluster.items():
        if len(names) < 2 and not any(
            normalize_title(n) in _CANON_DISPLAY for n in names
        ):
            # Single orphan with no canon map — skip
            continue
        # preferred_by_compact keys may need re-find after later unions
        pref = None
        for c, head in preferred_by_compact.items():
            if find(c) == root:
                pref = head
                break
        display = _pick_cluster_display(names, preferred=pref)
        if not display:
            continue
        preferred_slug = _pick_cluster_slug(names, display)
        if not preferred_slug:
            continue

        for n in names + [display]:
            c = identity_compact(n)
            if c:
                display_by_compact[c] = display
            s = slugify_series(n)
            if s and s != preferred_slug:
                # Don't clobber a more specific existing map to a *different* work
                existing = _KEY_SLUG_ALIASES.get(s)
                if existing and existing != preferred_slug:
                    continue
                slug_by_slug[s] = preferred_slug
        # Self map
        slug_by_slug.setdefault(preferred_slug, preferred_slug)

    _IDENTITY_DISPLAY_BY_COMPACT.clear()
    _IDENTITY_DISPLAY_BY_COMPACT.update(display_by_compact)
    _IDENTITY_SLUG_BY_SLUG.clear()
    _IDENTITY_SLUG_BY_SLUG.update(slug_by_slug)
    _identity_index_ready = True


def resolve_title_identity(title: str) -> Optional[str]:
    """
    Canonical display title when *title* is a known alternate name of a work.

    Combines English, romaji, and Japanese forms listed in TITLE_ALIASES /
    _CANON_DISPLAY (e.g. Welcome to the NHK ↔ NHK ni Youkoso! ↔ N・H・Kにようこそ).
    """
    raw = (title or "").strip()
    if not raw:
        return None
    _build_title_identity_index()
    # Direct canon map first (cheap path)
    key = normalize_title(raw)
    compact_spaces = re.sub(r"[\s\-_]+", " ", key).strip()
    if compact_spaces in _CANON_DISPLAY:
        return _CANON_DISPLAY[compact_spaces]
    ic = identity_compact(raw)
    if ic and ic in _IDENTITY_DISPLAY_BY_COMPACT:
        return _IDENTITY_DISPLAY_BY_COMPACT[ic]
    return None


def resolve_identity_slug(slug: str) -> Optional[str]:
    """Preferred series_key suffix when *slug* belongs to a known title cluster."""
    s = (slug or "").strip().lower()
    if not s:
        return None
    _build_title_identity_index()
    if s in _KEY_SLUG_ALIASES:
        return _KEY_SLUG_ALIASES[s]
    if s in _IDENTITY_SLUG_BY_SLUG:
        return _IDENTITY_SLUG_BY_SLUG[s]
    return None


def is_study_tool(
    title: str = "",
    *,
    source: str = "",
    series_key: str = "",
    content_type: str = "",
) -> bool:
    """True for Anki / Bunpro / Italki / similar tools."""
    src = (source or "").strip().lower()
    if src in _STUDY_SOURCES:
        return True
    ct = (content_type or "").strip().lower()
    if ct == "study" and _STUDY_TOOL_RE.search((title or "").strip()):
        return True
    blob = f"{title or ''} {series_key or ''}"
    # series_key like anime:anki / anime:bunpro
    sk = (series_key or "").strip().lower()
    if ":" in sk:
        suffix = sk.split(":", 1)[1]
        if suffix in ("anki", "bunpro", "italki", "wanikani") or suffix.startswith(
            ("anki-", "bunpro-", "italki-")
        ):
            return True
    return bool(_STUDY_TOOL_RE.search((title or "").strip())) or bool(
        _STUDY_TOOL_RE.search(blob.replace(":", " "))
    )


def is_non_work_entry(title: str = "", series_key: str = "") -> bool:
    """Contest carry-over, pure numbers, bonus lines — not shelf works."""
    t = (title or "").strip()
    sk = (series_key or "").strip()
    if not t and not sk:
        return True
    if re.fullmatch(r"\d{1,6}", t or ""):
        return True
    if re.fullmatch(r"(?:anime|other|show):?\d+", sk or "", re.I):
        return True
    if _NON_WORK_RE.search(t) or _NON_WORK_RE.search(sk.replace("-", " ")):
        return True
    # Empty / unknown keys
    if sk.endswith(":unknown") or sk in ("anime:1", "anime:unknown"):
        # [1巻] 無職転生 wrongly keyed as anime:1 — not non-work if title has real text
        if t and not re.fullmatch(r"\d+", t) and "[" not in t[:3]:
            return False
        if t and ("巻" in t or len(t) > 3):
            return False
        if sk == "anime:1" and t and not re.fullmatch(r"\d+", clean_search_title(t) or ""):
            return False
        if sk.endswith(":unknown"):
            return True
    return False


# Clear English / non-JP media that should never be Japanese immersion shelf items
_KNOWN_NON_JP_TITLES = frozenset(
    {
        "silo",
        "house of the dragon",
        "game of thrones",
        "breaking bad",
        "the last of us",
        "stranger things",
        "the witcher",
        "fallout",
        "the boys",
        "wednesday",  # Netflix Addams — not 水曜日のダウンタウン
        "succession",
        "the mandalorian",
        "andor",
        "foundation",
        "the expanse",
        "westworld",
        "chernobyl",
        "band of brothers",
        "the wire",
        "mad men",
        "friends",
        "the office",
        "seinfeld",
        "better call saul",
        "ozark",
        "narcos",
        "peaky blinders",
        "the crown",
        "bridgerton",
        "euphoria",
        "invincible",  # Amazon EN; JP dub still optional — keep list conservative
    }
)


def _norm_lang(lang: str) -> str:
    l = (lang or "").strip().lower()
    if l in ("ja", "jpn", "japanese", "jp", "jap"):
        return "ja"
    if l in ("en", "eng", "english", "en-us", "en-gb"):
        return "en"
    return l


def is_non_japanese_work(
    *,
    title: str = "",
    series_key: str = "",
    languages: Optional[set[str]] = None,
    tadoku_modes: Optional[set[str]] = None,
) -> bool:
    """
    True for English / non-JP media that should stay off the Progress shelf.

    Signals (any one is enough when japanese_only is on):
      - log language is non-Japanese (en, …) with no Japanese evidence
      - title/key matches a known Western show denylist
      - config exclude_titles / exclude_series_keys
      - optional: all logs are tadoku_mode=never *and* title looks Western (Latin-only show)
    """
    try:
        from app.core.config import get_settings

        pcfg = get_settings().yaml_config.progress
    except Exception:  # noqa: BLE001
        pcfg = None

    japanese_only = True if pcfg is None else bool(getattr(pcfg, "japanese_only", True))
    if not japanese_only:
        return False

    allowed = {
        _norm_lang(x)
        for x in (
            list(getattr(pcfg, "languages", None) or ["ja", "jpn", "japanese", "jp"])
        )
    }
    allowed.discard("")
    if not allowed:
        allowed = {"ja"}

    t = normalize_work_title(title) or (title or "")
    sk = (series_key or "").strip().lower()
    compact = normalize_title(t)

    # Config excludes
    for needle in list(getattr(pcfg, "exclude_titles", None) or []):
        n = (needle or "").strip().lower()
        if not n:
            continue
        if n in compact or n in (title or "").lower() or n in sk.replace("-", " "):
            return True
    for needle in list(getattr(pcfg, "exclude_series_keys", None) or []):
        n = (needle or "").strip().lower()
        if n and n == sk:
            return True

    # Built-in Western denylist (exact match only — avoid "wednesday" ⊂ 水曜日の…)
    if compact in _KNOWN_NON_JP_TITLES:
        return True
    # Multi-word denylist: allow "house of the dragon s2" style tails only
    for bad in _KNOWN_NON_JP_TITLES:
        if " " not in bad:
            continue
        if compact == bad or compact.startswith(bad + " "):
            return True

    langs = {_norm_lang(x) for x in (languages or set()) if x}
    # Explicit non-JP language on logs, with no JP signal
    non_jp = {x for x in langs if x and x not in allowed}
    has_jp = bool(langs & allowed) or bool(
        re.search(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]", t)
    )
    if non_jp and not has_jp:
        return True

    # Tadoku "never" on every log + Latin-only Western-looking title → hide
    hide_never = True if pcfg is None else bool(getattr(pcfg, "hide_tadoku_never", True))
    modes = {m.strip().lower() for m in (tadoku_modes or set()) if m}
    if hide_never and modes and modes <= {"never"} and not has_jp:
        # Only hide if it also looks like pure English entertainment (not romaji anime)
        # Heuristic: denylist OR (content is show-like key and multi-word English)
        if compact in _KNOWN_NON_JP_TITLES:
            return True
        if sk.startswith("show:") or "house-of-the-dragon" in sk or sk.endswith(":silo"):
            return True
        # Explicit: common EN show keys after normalize
        for bad in ("silo", "house-of-the-dragon", "game-of-thrones"):
            if bad in sk:
                return True

    return False


def is_progress_shelf_work(
    *,
    title: str = "",
    content_type: str = "",
    source: str = "",
    series_key: str = "",
    languages: Optional[set[str]] = None,
    tadoku_modes: Optional[set[str]] = None,
) -> bool:
    """
    Whether this work belongs on the Progress library shelf.

    Excludes: youtube, study tools, contest carry-overs, garbage keys,
    and non-Japanese media when progress.japanese_only is enabled.
    """
    ct = (content_type or "").strip().lower()
    if ct == "youtube":
        return False
    if is_study_tool(title, source=source, series_key=series_key, content_type=ct):
        return False
    if ct == "study":
        # Remaining study (non-tool) still off the content shelf
        return False
    if is_non_work_entry(title, series_key):
        return False
    if is_non_japanese_work(
        title=title,
        series_key=series_key,
        languages=languages,
        tadoku_modes=tadoku_modes,
    ):
        return False
    return True


def normalize_work_title(title: str) -> str:
    """
    Collapse log lines to a shelf work name.

    ``One Piece 19 (218 pages]`` → ``One Piece``
    ``Attack On Titan E1-E17`` → ``Attack On Titan``
    ``Gachiakuta 2,3`` → ``Gachiakuta``
    """
    from app.media.progress_fixup import split_embedded_episode

    raw = title or ""
    # Prefer embedded episode peel first so "Gachiakuta 2,3" never sticks
    peeled = split_embedded_episode(raw)
    if peeled.get("matched") and peeled.get("title"):
        raw = peeled["title"]

    t = clean_search_title(raw)
    t = _PAGE_PAREN.sub("", t)
    t = _TRAILING_JUNK.sub("", t)
    t = re.sub(r"\s+", " ", t).strip(" -–—·|[]【】")
    # Repair accidental strip of leading "1" from "1,000,000 …"
    if t.startswith(",000") or t.startswith(",0"):
        t = "1" + t
    # "Wednesday Downtown: Monster House" → base show before colon when known
    if ":" in t and not re.search(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]", t):
        head, tail = t.split(":", 1)
        head_n = normalize_title(head)
        if head_n in _CANON_DISPLAY or any(
            head_n == a or head_n.startswith(a + " ") for a in _CANON_DISPLAY
        ):
            t = head.strip()
    if not t:
        return ""
    # Canon display names (exact, or alias + volume/episode noise only)
    key = normalize_title(t)
    compact = re.sub(r"[\s\-_]+", " ", key).strip()
    if compact in _CANON_DISPLAY:
        return _CANON_DISPLAY[compact]
    for alias, display in _CANON_DISPLAY.items():
        if compact == alias:
            return display
        if compact.startswith(alias + " "):
            rest = compact[len(alias) + 1 :].strip()
            # Only collapse pure volume/episode leftovers — not "film red", "daima", etc.
            if re.fullmatch(
                r"(?:vol(?:ume)?\.?\s*)?\d+(?:\s*(?:half|pages?|話|巻))?|"
                r"\d{1,3}(?:\s*[,，]\s*\d{1,3})+|"
                r"e\d+(?:\s*[-–]\s*e?\d+)?|"
                r"s\d+(?:e\d+)?(?:\s*[-+&]\s*s?\d+)?|"
                r"half|page.*",
                rest,
                re.I,
            ):
                return display
    # EN / JP / romaji cluster (TITLE_ALIASES + compact punctuation match)
    identified = resolve_title_identity(t)
    if identified:
        return identified
    return t


def _slug_alias(slug: str) -> str:
    s = (slug or "").strip().lower()
    # Preserve CJK in aliases map (lower() is no-op for kana/kanji)
    s_raw = (slug or "").strip()
    if s in _KEY_SLUG_ALIASES:
        return _KEY_SLUG_ALIASES[s]
    if s_raw in _KEY_SLUG_ALIASES:
        return _KEY_SLUG_ALIASES[s_raw]
    # Strip common fragment suffixes from slug
    s2 = re.sub(
        r"-(?:vol(?:ume)?(?:-\d+)?|half|page.*|s\d+e\d+.*|e\d+-\d+|s\d+-s\d+|"
        r"\d+-pages?|double|correcting.*|from-switch.*|chapter|ch)$",
        "",
        s,
    )
    # Trailing volume/chapter ranges: foo-9-10, foo-1-8 (not years)
    s3 = re.sub(r"-(?!19\d{2}$|20\d{2}$)(\d{1,3})(?:-(\d{1,3}))?$", "", s2)
    for candidate in (s3, s2):
        if candidate in _KEY_SLUG_ALIASES:
            return _KEY_SLUG_ALIASES[candidate]
    # Cluster-derived redirects (NHK ni Youkoso → welcome-to-the-nhk, etc.)
    _build_title_identity_index()
    for candidate in (s3, s2, s, s_raw):
        if not candidate:
            continue
        mapped = _IDENTITY_SLUG_BY_SLUG.get(candidate)
        if mapped:
            return mapped
        mapped = _KEY_SLUG_ALIASES.get(candidate)
        if mapped:
            return mapped
    return s3 or s2 or s


def _known_type_for(title: str = "", series_key: str = "") -> Optional[str]:
    """Return forced content_type when title/key matches a known work."""
    work = normalize_title(normalize_work_title(title) or title or "")
    if work in _KNOWN_CONTENT_TYPES:
        return _KNOWN_CONTENT_TYPES[work]
    compact = re.sub(r"[\s\-_]+", " ", work).strip()
    if compact in _KNOWN_CONTENT_TYPES:
        return _KNOWN_CONTENT_TYPES[compact]
    sk = (series_key or "").strip().lower()
    if ":" in sk:
        slug = sk.split(":", 1)[1]
        aliased = _slug_alias(slug).replace("-", " ")
        if aliased in _KNOWN_CONTENT_TYPES:
            return _KNOWN_CONTENT_TYPES[aliased]
        if slug.replace("-", " ") in _KNOWN_CONTENT_TYPES:
            return _KNOWN_CONTENT_TYPES[slug.replace("-", " ")]
    return None


def infer_content_type(
    title: str,
    content_type: str,
    *,
    source: str = "",
    series_key: str = "",
    unit: str = "",
    activity: str = "",
) -> str:
    """
    Normalize type: study tools → study; fix reading vs listening mismatches.

    Pages/characters + reading must not stay under anime:… keys (Dandadan case).
    """
    if is_study_tool(title, source=source, series_key=series_key, content_type=content_type):
        return "study"
    ct = (content_type or "other").strip().lower()
    sk = (series_key or "").strip().lower()
    if sk.startswith("vn:") or sk.startswith("gsm:"):
        return "visual_novel"
    if sk.startswith("yt:"):
        return "youtube"
    if ct in ("vn",):
        return "visual_novel"
    if ct in ("audio_book", "audio-book"):
        return "audiobook"

    # Unit / activity trump a wrong category (unless locked strong types)
    unit_l = (unit or "").strip().lower()
    act = (activity or "").strip().lower()
    title_l = (title or "").lower()
    reading_units = {
        "pages",
        "comic_pages",
        "two_column_pages",
        "characters",
        "sentences",
    }
    listening_units = {"minutes", "minutes_high_density"}
    looks_vol = bool(re.search(r"\bvol(?:ume)?\.?\b|\bpage\b|巻|頁", title_l, re.I))

    if ct not in ("youtube", "podcast", "game", "visual_novel", "study", "audiobook"):
        if unit_l in reading_units or act == "reading" or looks_vol:
            if ct in ("other", "anime", "show", "movie", ""):
                ct = "manga"
        elif unit_l in listening_units or act == "listening":
            if ct in ("other", "manga", "book", ""):
                ct = "anime"

    # Known title forces (MAD manga, Arcane show, film red movie, …) after unit inference
    known = _known_type_for(title, series_key)
    if known:
        # Don't force anime for a clear page-reading log of the same franchise
        if known == "anime" and (
            unit_l in reading_units or act == "reading" or looks_vol
        ):
            return "manga"
        if known == "manga" and (
            unit_l in listening_units or act == "listening"
        ) and not looks_vol:
            return "anime"
        return known

    # Unambiguous film/movie titles (One Piece Film Red, “… the Movie”, 映画)
    # Prefer movie over anime/show so metadata hits theatrical entries, not 1000-ep TV.
    work = normalize_work_title(title) or title or ""
    if ct in ("anime", "show", "other", "") and _MOVIE_TITLE_RE.search(work):
        # Don't reclassify multi-episode series logs that only mention "film" in notes
        if not re.search(r"\bS\d{1,2}E\d{1,3}\b|\bE\d{2,3}\b", title or "", re.I):
            return "movie"

    return ct or "other"


def looks_like_fragment_key(series_key: str) -> bool:
    """True when series_key encodes volume/episode/log noise."""
    sk = (series_key or "").strip().lower()
    sk_raw = (series_key or "").strip()
    if not sk or ":" not in sk:
        return False
    slug = sk.split(":", 1)[1]
    slug_raw = sk_raw.split(":", 1)[1] if ":" in sk_raw else slug
    if slug in _KEY_SLUG_ALIASES or slug_raw in _KEY_SLUG_ALIASES:
        return True
    if _slug_alias(slug_raw) != slug and _slug_alias(slug_raw) != slug_raw:
        return True
    if _slug_alias(slug) != slug:
        return True
    if re.search(
        r"(?:^|-)(?:vol|volume|page|pages|half|double|correcting|from-switch|"
        r"chapter|ch|s\d{1,2}e\d{1,3}|e\d{1,3}-\d{1,3}|s\d+-s\d+|"
        r"\d{1,3}-pages?)(?:-|$)",
        slug,
    ):
        return True
    if re.search(r"-\d{1,3}(?:-\d{1,3})?$", slug) and not re.search(
        r"(?:19\d{2}|20\d{2})$", slug
    ):
        return True
    return False


def needs_key_rewrite(series_key: str, title: str = "") -> bool:
    """
    True when a key should be rebuilt even if it looks 'clean'.

    Catches CJK slug aliases (とつくにの少女 → totsukuni-no-shoujo),
    type-prefix drift, and known slug maps.
    """
    sk = (series_key or "").strip()
    if not sk or ":" not in sk:
        return True
    if looks_like_fragment_key(sk):
        return True
    prefix, slug = sk.split(":", 1)
    aliased = _slug_alias(slug)
    if aliased != slug:
        return True
    known_ct = _known_type_for(title, sk)
    if known_ct and prefix not in (known_ct, "study", "yt") and known_ct != "other":
        # anime:mad while known manga → rewrite
        if prefix in ("anime", "other", "show") and known_ct in (
            "manga",
            "game",
            "show",
            "audiobook",
            "book",
        ):
            return True
    # CJK in slug with a latin canon available
    if re.search(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]", slug):
        work = normalize_work_title(title) or title
        nt = normalize_title(work)
        for alias, display in _CANON_DISPLAY.items():
            if normalize_title(display) == nt and re.search(r"[A-Za-z]", alias):
                return True
    return False


def canonical_series_key(
    content_type: str,
    title: str,
    *,
    existing_key: str = "",
    source: str = "",
    prefer_existing: bool = False,
) -> str:
    """
    Stable series_key for a work (never volume/episode-specific).

    Example: anime:one-piece-19-… → anime:one-piece

    When prefer_existing and the key is already clean, keep it (ingest/catalog).
    """
    ct = infer_content_type(
        title, content_type, source=source, series_key=existing_key
    )
    raw = (existing_key or "").strip()

    if is_study_tool(title, source=source, series_key=raw, content_type=ct):
        m = _STUDY_TOOL_RE.match((title or "").strip())
        work_title = (m.group(0) if m else normalize_work_title(title) or "study")
        return suggest_series_key("study", work_title)

    if prefer_existing and raw and not needs_key_rewrite(raw, title):
        if not raw.startswith("gsm:"):
            return raw

    work_title = normalize_work_title(title)
    if not work_title and raw and ":" in raw:
        suffix = raw.split(":", 1)[1].replace("-", " ")
        work_title = normalize_work_title(suffix) or suffix
    if not work_title:
        work_title = (title or "unknown").strip() or "unknown"

    # Re-infer type from cleaned title (MAD / とつくに / Arcane / …)
    ct = infer_content_type(
        work_title, ct, source=source, series_key=raw
    )

    # Latin alias for stable key when display is long JP form
    key_title = work_title
    nt = normalize_title(work_title)
    for alias, display in _CANON_DISPLAY.items():
        if normalize_title(display) == nt and re.search(r"[A-Za-z]", alias):
            key_title = alias
            break

    key = suggest_series_key(ct, key_title)
    if ":" in key:
        prefix, slug = key.split(":", 1)
        slug = _slug_alias(slug)
        if raw and ":" in raw:
            old_slug = raw.split(":", 1)[1]
            aliased = _slug_alias(old_slug)
            if aliased != old_slug:
                slug = aliased
        # Prefer known forced type for prefix when set
        known_ct = _known_type_for(work_title, raw)
        if known_ct:
            prefix = known_ct
        key = f"{prefix}:{_slug_alias(slug)}"
    return key


def peel_log_fields(title: str) -> dict[str, Any]:
    """
    From a messy log title, return cleaned work title + optional season/episode.

    Volume + page ranges never put page numbers into episode
    (``vol 1 page 50-100`` → volume 1, not E100).
    """
    from app.media.progress_fixup import split_embedded_episode

    raw = title or ""
    cleaned = normalize_work_title(raw) or clean_search_title(raw) or raw.strip()

    # Volume + optional page range first
    m = re.match(
        r"^(?P<title>.+?)\s+(?:vol(?:ume)?\.?|第)\s*(?P<vol>\d{1,4})\s*"
        r"(?:pages?\s*\d{1,5}\s*[-–~～to]+\s*\d{1,5}|"
        r"[\(（]\s*\d{1,5}\s*(?:to|[-–~～])\s*\d{1,5}\s*[\)）])?\s*$",
        raw.strip(),
        re.I,
    )
    if m:
        vol = int(m.group("vol"))
        base = normalize_work_title(m.group("title")) or m.group("title").strip()
        return {
            "title": base or cleaned,
            "season": None,
            "episode": vol,  # volume number for manga shelf position
            "volume": vol,
            "kind": "volume",
            "matched": True,
        }

    # Don't treat "page 50-100" tails as episode ranges
    if re.search(r"\bpage\b|頁", raw, re.I):
        return {
            "title": cleaned,
            "season": None,
            "episode": None,
            "volume": None,
            "kind": "pages",
            "matched": cleaned != raw.strip(),
        }

    peeled = split_embedded_episode(raw)
    season = peeled.get("season")
    episode = peeled.get("episode") if peeled.get("matched") else None
    # Prefer peeled base title when episode range was stripped ("Gachiakuta 2,3")
    if peeled.get("matched") and peeled.get("title"):
        cleaned = (
            normalize_work_title(peeled["title"])
            or clean_search_title(peeled["title"])
            or peeled["title"]
        )
    # Volume number as episode for manga-style "One Piece 19" / "第3巻"
    if episode is None:
        m = re.search(
            r"(?:vol(?:ume)?\.?\s*|第)(\d{1,3})\s*(?:巻)?\s*$",
            clean_search_title(raw) or raw,
            re.I,
        )
        if m and cleaned and cleaned != raw.strip():
            try:
                episode = int(m.group(1))
            except ValueError:
                episode = None
            return {
                "title": cleaned,
                "season": None,
                "episode": episode,
                "volume": episode,
                "kind": "volume" if episode is not None else "plain",
                "matched": episode is not None,
            }
    return {
        "title": cleaned,
        "season": season,
        "episode": episode,
        "volume": None,
        "kind": "episode" if episode is not None else "plain",
        "matched": bool(
            peeled.get("matched") or (episode is not None and cleaned != raw.strip())
        ),
    }


def prepare_log_identity(
    *,
    content_type: str,
    title: str,
    source: str = "",
    series_key: Optional[str] = None,
    season: Optional[int] = None,
    episode: Optional[int] = None,
    unit: str = "",
    activity: str = "",
) -> dict[str, Any]:
    """
    Normalize fields before create_log / ingest.

    Returns content_type, title, series_key, season, episode.
    """
    peeled = peel_log_fields(title)
    work_title = peeled["title"] or (title or "").strip() or "Unknown"
    ct = infer_content_type(
        work_title,
        content_type,
        source=source,
        series_key=series_key or "",
        unit=unit,
        activity=activity,
    )
    # Prefer explicit season/episode from caller; fill from title peel if missing
    se = season if season is not None else peeled.get("season")
    ep = episode if episode is not None else peeled.get("episode")
    # Volume logs: never keep a page-range as episode if peel says volume
    if peeled.get("kind") == "volume" and peeled.get("volume") is not None:
        ep = int(peeled["volume"])
        se = None
    if peeled.get("kind") == "pages":
        # page-only titles without vol — clear bogus episode
        if episode is None:
            ep = None

    raw_key = (series_key or "").strip()
    # Reading vs listening must not share anime:/manga: prefix
    prefer = True
    if raw_key and ":" in raw_key:
        pref, slug = raw_key.split(":", 1)
        pref_l = pref.lower()
        rewritable = {
            "anime",
            "show",
            "manga",
            "book",
            "audiobook",
            "game",
            "movie",
            "other",
            "podcast",
        }
        if pref_l in rewritable and pref_l != ct:
            raw_key = f"{ct}:{slug}"
            prefer = False

    key = canonical_series_key(
        ct,
        work_title,
        existing_key=raw_key,
        source=source,
        prefer_existing=prefer,
    )

    return {
        "content_type": ct,
        "title": work_title,
        "series_key": key,
        "season": se,
        "episode": ep,
    }
