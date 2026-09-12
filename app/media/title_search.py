"""Title cleaning and expansion for external media metadata lookup."""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

from app.media.catalog_resolve import normalize_title

# Common immersion-log abbreviations / nicknames → search forms
TITLE_ALIASES: dict[str, list[str]] = {
    "aot": ["Attack on Titan", "Shingeki no Kyojin", "進撃の巨人"],
    "snk": ["Attack on Titan", "Shingeki no Kyojin", "進撃の巨人"],
    "gto": ["GTO", "Great Teacher Onizuka"],
    "bookworm": ["Ascendance of a Bookworm", "Honzuki no Gekokujou", "本好きの下剋上"],
    "honzuki": ["Ascendance of a Bookworm", "本好きの下剋上"],
    "yanineko": ["Yani Neko", "ヤニねこ", "Chainsmoker Cat"],
    "yani neko": ["Yani Neko", "ヤニねこ", "Chainsmoker Cat"],
    "mahoyo": ["Mahoutsukai no Yoru", "Witch on the Holy Night", "魔法使いの夜"],
    "demonbane": ["Demonbane", "斬魔大聖デモンベイン"],
    "steins gate": ["Steins;Gate", "シュタインズ・ゲート"],
    "steins;gate": ["Steins;Gate", "シュタインズ・ゲート"],
    "steinsgate": ["Steins;Gate", "シュタインズ・ゲート"],
    "gashiakuta": ["Gachiakuta", "ガチアクタ"],
    "gachiakuta": ["Gachiakuta", "ガチアクタ"],
    "nhk": [
        "Welcome to the NHK",
        "NHK ni Youkoso",
        "NHK ni Youkoso!",
        "N.H.K. ni Youkoso",
        "N.H.K ni Youkoso",
        "N・H・Kにようこそ",
        "NHKにようこそ",
    ],
    "n-h-k": [
        "Welcome to the NHK",
        "NHK ni Youkoso",
        "N.H.K. ni Youkoso",
        "N・H・Kにようこそ",
    ],
    "welcome to the n-h-k": [
        "Welcome to the NHK",
        "NHK ni Youkoso",
        "N・H・Kにようこそ",
    ],
    "welcome to the nhk": [
        "Welcome to the NHK",
        "NHK ni Youkoso",
        "N・H・Kにようこそ",
    ],
    "nhk ni youkoso": [
        "Welcome to the NHK",
        "NHK ni Youkoso",
        "N.H.K. ni Youkoso",
        "N・H・Kにようこそ",
    ],
    "eizouken": ["Keep Your Hands Off Eizouken!", "映像研には手を出すな!"],
    "ping pong": ["Ping Pong the Animation", "ピンポン"],
    "hyouka": ["Hyouka", "氷菓"],
    "mushoku tensei": [
        "Mushoku Tensei",
        "無職転生",
        "無職転生 ～異世界行ったら本気だす～",
        "Mushoku Tensei: Jobless Reincarnation",
    ],
    "musyoku tensei": ["Mushoku Tensei", "無職転生"],
    "無職転生": [
        "無職転生",
        "Mushoku Tensei",
        "無職転生 ～異世界行ったら本気だす～",
        "Mushoku Tensei: Jobless Reincarnation",
    ],
    "frieren": ["Frieren", "Sousou no Frieren", "葬送のフリーレン"],
    "arcane": [
        "Arcane",
        "Arcane: League of Legends",
        "Arcane League of Legends",
    ],
    "silo": ["Silo"],
    "house of the dragon": ["House of the Dragon"],
    "wednesday downtown": ["Wednesday Downtown"],
    "re:zero": ["Re:Zero", "Re:Zero kara Hajimeru Isekai Seikatsu", "Reゼロから始める異世界生活"],
    "rezero": ["Re:Zero", "Reゼロから始める異世界生活"],
    "one piece": ["One Piece", "ワンピース"],
    # Distinct movie — never expand into the TV series via bare "one piece"
    "one piece red": [
        "ONE PIECE FILM RED",
        "One Piece Film: Red",
        "One Piece Film Red",
        "ワンピース フィルム レッド",
    ],
    "one piece film red": [
        "ONE PIECE FILM RED",
        "One Piece Film: Red",
        "One Piece Film Red",
        "ワンピース フィルム レッド",
    ],
    "onepiecered": [
        "ONE PIECE FILM RED",
        "One Piece Film: Red",
        "ワンピース フィルム レッド",
    ],
    "konosuba": [
        "この素晴らしい世界に祝福を！",
        "KonoSuba",
        "Kono Subarashii Sekai ni Shukufuku wo!",
        "KONOSUBA -God's blessing on this wonderful world!",
    ],
    "この素晴らしい世界に祝福を": [
        "この素晴らしい世界に祝福を！",
        "KonoSuba",
        "Kono Subarashii Sekai ni Shukufuku wo!",
    ],
    "dandadan": ["Dandadan", "ダンダダン"],
    "ダンダダン": ["Dandadan", "ダンダダン"],
    "dbz": ["Dragon Ball Z", "ドラゴンボールZ"],
    "db daima": ["Dragon Ball Daima", "ドラゴンボールDAIMA"],
    "daima": ["Dragon Ball Daima", "ドラゴンボールDAIMA"],
    "vineland saga": ["Vinland Saga", "ヴィンランド・サガ"],
    "vinland saga": ["Vinland Saga", "ヴィンランド・サガ"],
    "hajime no ippo": [
        "Hajime no Ippo",
        "はじめの一歩",
        "Hajime no Ippo: THE FIGHTING!",
        "はじめの一歩 THE FIGHTING!",
    ],
    "はじめの一歩": [
        "はじめの一歩",
        "Hajime no Ippo",
        "Hajime no Ippo: THE FIGHTING!",
    ],
    "made in abyss": ["Made in Abyss", "メイドインアビス"],
    "13 sentinels": ["13 Sentinels: Aegis Rim", "十三機兵防衛圏"],
    "tsukihime": ["Tsukihime", "月姫"],
    "trails in the sky": ["The Legend of Heroes: Trails in the Sky", "英雄伝説 空の軌跡"],
    "hogwards legacy": ["Hogwarts Legacy"],  # common misspelling
    "hogwarts legacy": ["Hogwarts Legacy"],
    "first of the north star": ["Fist of the North Star", "北斗の拳"],
    "fist of the north star": ["Fist of the North Star", "北斗の拳"],
    "terrace house": ["Terrace House"],
    "muramasa": ["Muramasa: The Demon Blade", "朧村正"],
    "yugi": [
        "Yu-Gi-Oh!",
        "Yu-Gi-Oh! Duel Monsters",
        "Yu☆Gi☆Oh! Duel Monsters",
        "遊☆戯☆王",
        "遊☆戯☆王デュエルモンスターズ",
        "遊☆戯☆王　デュエルモンスターズ",
    ],
    "yu gi oh": [
        "Yu-Gi-Oh!",
        "Yu-Gi-Oh! Duel Monsters",
        "遊☆戯☆王デュエルモンスターズ",
    ],
    "yu-gi-oh": [
        "Yu-Gi-Oh!",
        "Yu-Gi-Oh! Duel Monsters",
        "遊☆戯☆王デュエルモンスターズ",
    ],
    "遊戯王": [
        "遊☆戯☆王",
        "Yu-Gi-Oh!",
        "Yu-Gi-Oh! Duel Monsters",
        "遊☆戯☆王デュエルモンスターズ",
    ],
    "chi": ["Chi's Sweet Home", "チーズスイートホーム"],
    "とつくにの少女": [
        "とつくにの少女",
        "Totsukuni no Shoujo",
        "The Girl from the Other Side",
        "The Girl From the Other Side: Siúil, a Rún",
    ],
    "totsukuni no shoujo": [
        "とつくにの少女",
        "Totsukuni no Shoujo",
        "The Girl from the Other Side",
    ],
    "the girl from the other side": [
        "The Girl from the Other Side",
        "とつくにの少女",
        "Totsukuni no Shoujo",
    ],
    "mad": ["MAD"],
    "mad chapter": ["MAD"],
    "mad ch": ["MAD"],
}

# Strip season/episode range tails and volume prefixes from search titles
_RANGE_TAIL = re.compile(
    r"""
    \s*
    (?:
        [Ss]\d{1,2}\s*[+&]\s*[Ss]\d{1,2}          # S1+S2
      | [Ss]\d{1,2}\s*[-–]\s*[Ss]?\d{1,2}         # S1-S2
      | [Ee]?\d{1,3}\s*[-–~～]\s*[Ee]?\d{1,3}     # E1-E17 / 1-17
      | [Ss]\d{1,2}[Ee]\d{1,3}(?:\s*[-–]\s*(?:[Ss]\d{1,2})?[Ee]?\d{1,3})?
      | Vol\.?\s*\d+(?:\s*[-–]\s*\d+)?
      | 第?\d+\s*[-–~～]\s*\d+\s*[話巻話]?
    )
    \s*$
    """,
    re.I | re.X,
)
# Only strip explicit volume markers — never a bare leading digit ("1,000,000 yen…")
_VOL_PREFIX = re.compile(
    r"^\s*(?:"
    r"[\[【\(]\s*(?:vol\.?|volume|第)?\s*\d+\s*[巻話]?\s*[\]】\)]\s*"
    r"|(?:vol\.?|volume|第)\s*\d+\s*[巻話]?\s+"
    r")",
    re.I,
)
_EP_IN_MIDDLE = re.compile(
    r"\s+[Ss]\d{1,2}[Ee]\d{1,3}\b.*$",
    re.I,
)
_FINISHED_TAIL = re.compile(
    r"\s*[-–]?\s*(?:finished|完|読了|クリア)\s*$",
    re.I,
)
_HOURS_NOISE = re.compile(
    r"\s+\d+(?:\.\d+)?\s*[kx]?\s*(?:x\s*)?\d*\s*(?:hours?|hrs?|時間).*$",
    re.I,
)
_PR_PREFIX = re.compile(r"^\s*PR\s*:\s*", re.I)
# Manual log notes that trail the real title
_LOG_NOTE_TAIL = re.compile(
    r"""
    \s*
    (?:
        [-–—|·]\s*
      | \(\s*
    )?
    (?:
        from\s+switch
      | char(?:acter)?s?\s*count
      | estimate
      | half(?:\s*pts?)?
      | double(?:\s*pts?)?
      | true\s*ending
      | good\s*ending
      | missed
    )
    .*
    $
    """,
    re.I | re.X,
)


def clean_search_title(title: str) -> str:
    """Strip logging noise so providers see a real work name."""
    t = unicodedata.normalize("NFKC", (title or "").strip())
    if not t:
        return t
    from app.media.metadata_cache import strip_contest_noise

    t = strip_contest_noise(t)
    t = _PR_PREFIX.sub("", t)
    t = _VOL_PREFIX.sub("", t)
    t = _RANGE_TAIL.sub("", t)
    t = _EP_IN_MIDDLE.sub("", t)
    t = _FINISHED_TAIL.sub("", t)
    t = _HOURS_NOISE.sub("", t)
    t = _LOG_NOTE_TAIL.sub("", t)
    # "Attack On Titan E1-E17" leftover
    t = re.sub(r"\s+[Ee]\d{1,3}\s*[-–]\s*[Ee]?\d{1,3}\s*$", "", t)
    # "One Piece 31 half" / "One Piece vol 11 page" / "Made In Abyss Vol 1 Page<0,26>"
    t = re.sub(
        r"\s+(?:vol(?:ume)?\.?\s*)?\d+\s*(?:half|page|pages?|話|巻).*$",
        "",
        t,
        flags=re.I,
    )
    t = re.sub(r"\s+vol(?:ume)?\.?\s*\d*\s*$", "", t, flags=re.I)
    t = re.sub(r"\s+S\d+(?:\s*,\s*S\d+)*\s*$", "", t, flags=re.I)
    t = re.sub(r"\s+Season\s*\d*\s*$", "", t, flags=re.I)
    t = re.sub(r"\s+Page\s*<[^>]*>\s*$", "", t, flags=re.I)
    t = re.sub(r"\s+Challenge\s+Bonus.*$", "", t, flags=re.I)
    t = re.sub(r"\s+\d+\s*&\s*$", "", t)  # "DBZ 4 &"
    # Character-count log tails: "Demonbane 53099 x 2" → "Demonbane"
    t = re.sub(r"\s+\d{3,}\s*[x×]\s*\d+\s*$", "", t, flags=re.I)
    t = re.sub(r"\s+\d{4,}\s*$", "", t)  # bare large character counts
    # "MAD chapter" / "mad ch 9" / "MAD chapter 4-8" → "MAD"
    t = re.sub(
        r"\s+ch(?:apter)?s?(?:\s+\d+(?:\s*[-–~～]\s*\d+)?)?\s*$",
        "",
        t,
        flags=re.I,
    )
    # Episode lists / ranges: "Gachiakuta 2,3" / "GTO 5, 6" / "Show 1-3"
    t = re.sub(
        r"\s+\d{1,3}(?:\s*,\s*\d{1,3})+\s*$",
        "",
        t,
    )
    # JP/ASCII volume or episode ranges after title: "とつくにの少女 9-10" / "1-8"
    t = re.sub(
        r"\s+\d{1,3}\s*[-–~～]\s*\d{1,3}\s*$",
        "",
        t,
    )
    # Trailing volume/chapter/episode number: "One Piece 31" → "One Piece"
    m = re.match(r"^(.+?)\s+\d{1,4}$", t)
    if m and len(m.group(1)) >= 4 and not re.search(r"\d", m.group(1)[-3:]):
        t = m.group(1)
    # Cap absurdly long titles (keep head for providers)
    if len(t) > 80:
        t = t[:80].rsplit(" ", 1)[0] or t[:80]
    t = re.sub(r"\s{2,}", " ", t).strip(" -–—·|")
    return t or (title or "").strip()


# Extra tokens after a franchise alias that mean a *different* work (movie, arc, …)
_ALIAS_DISTINCT_REST = re.compile(
    r"^(?:"
    r"film\b|movie\b|映画|"
    r"film\s*red|red\b|"  # One Piece Red / Film Red
    r"daima\b|z\b|gt\b|super\b|"
    r"legend\b|ova\b|special\b|movie\s+\d+"
    r")",
    re.I,
)
# Rest after alias is only volume/episode noise → still the same work
_ALIAS_NOISE_REST = re.compile(
    r"^(?:"
    r"(?:vol(?:ume)?\.?\s*)?\d+(?:\s*(?:half|pages?|話|巻))?|"
    r"e\d+(?:\s*[-–]\s*e?\d+)?|"
    r"s\d+(?:e\d+)?(?:\s*[-+&]\s*s?\d+)?|"
    r"half|page.*"
    r")$",
    re.I,
)


def _alias_applies_to_query(query_key: str, alias_key: str) -> bool:
    """
    True when query is this alias (or alias + volume noise).

    False when the query is a distinct subtitled work ("One Piece Film Red"
    must not expand via the bare "one piece" alias into the TV series).
    """
    if not query_key or not alias_key:
        return False
    if query_key == alias_key:
        return True
    if not query_key.startswith(alias_key + " "):
        return False
    rest = query_key[len(alias_key) + 1 :].strip()
    if not rest:
        return True
    if _ALIAS_DISTINCT_REST.match(rest):
        return False
    if _ALIAS_NOISE_REST.fullmatch(rest):
        return True
    # Unknown subtitle — treat as distinct work, do not expand parent alias
    return False


def identity_compact(name: str) -> str:
    """
    Punctuation-insensitive compact form for alternate-title matching.

    ``NHK ni Youkoso!`` ≈ ``N.H.K. ni Youkoso`` ≈ ``welcome to the n-h-k`` (spaces/hyphens only).
    Keeps CJK letters so JP titles stay distinct from romaji.
    """
    s = normalize_title(name)
    return re.sub(r"[^\w]+", "", s, flags=re.UNICODE).replace("_", "")


def expand_title_aliases(title: str) -> list[str]:
    """Return known longer names for nicknames / abbreviations."""
    cleaned = clean_search_title(title)
    key = normalize_title(cleaned)
    compact = re.sub(r"[\s\-_]+", "", key)
    ic = identity_compact(cleaned)
    out: list[str] = []
    for alias_key, names in TITLE_ALIASES.items():
        ak = normalize_title(alias_key)
        ac = re.sub(r"[\s\-_]+", "", ak)
        name_keys = {normalize_title(n) for n in names}
        name_compacts = {re.sub(r"[\s\-_]+", "", nk) for nk in name_keys}
        name_identity = {identity_compact(n) for n in names}
        name_identity.add(identity_compact(alias_key))
        if (
            key == ak
            or compact == ac
            or _alias_applies_to_query(key, ak)
            or key in name_keys
            or compact in name_compacts
            or (ic and ic in name_identity)
        ):
            out.extend(names)
            # Include the alias key itself when it is a real name form
            if re.search(r"[A-Za-z\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]", alias_key):
                out.append(alias_key)
    # Unique preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for n in out:
        nk = normalize_title(n)
        if nk and nk not in seen:
            seen.add(nk)
            uniq.append(n)
    return uniq


def is_weak_search_title(title: str) -> bool:
    """True for titles that are almost certainly not a real work name."""
    t = clean_search_title(title)
    if not t:
        return True
    if re.fullmatch(r"\d{1,6}", t):
        return True
    if len(t) <= 1:
        return True
    return False
