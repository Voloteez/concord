"""Deterministic checks: numbers, dates, currency (see CONTRACT.md).

run_checks(alignment, idx_en, idx_zh, languages=None) -> list of finding dicts WITHOUT severity/status:
  {type, source:"deterministic", pair_id, section, en:{page,text,span}, zh:{page,text,span},
   explanation, confidence}

"en" / "zh" are the two upload SLOTS. `languages` ({"en": detect result, "zh": detect result}) picks the
number / date / currency rules per side: English (default for unknown Latin languages), Chinese (also used
for Japanese), and French / German / Italian / Spanish / Portuguese / Dutch locale rules.
Pure Python + regex + cn2an. No LLM.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

try:
    import cn2an  # type: ignore
except Exception:  # pragma: no cover - cn2an is installed per CONTRACT.md
    cn2an = None

try:
    from extract import DEFAULT_LANGUAGES, joiner, short_name
except Exception:  # pragma: no cover - checks must stay importable on its own
    DEFAULT_LANGUAGES = {"en": {"code": "en", "name": "English", "script": "Latn"},
                         "zh": {"code": "zh", "name": "Chinese", "script": "Hant"}}

    def joiner(language):
        return "" if (language or {}).get("script") in ("Hani", "Hant", "Hans", "Jpan") else " "

    def short_name(language, fallback=""):
        name = (language or {}).get("name") or fallback
        return name.split(" (")[0] if name else fallback

# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------


@dataclass
class Num:
    value: float
    span: tuple[int, int]
    raw: str
    kind: str            # "plain" | "scaled" | "pct" | "cjk"
    currency: str | None = None
    mult_word: str | None = None   # "million" / "萬" ... used to phrase explanations


@dataclass
class Date:
    iso: str
    span: tuple[int, int]
    raw: str


@dataclass
class Cur:
    code: str
    span: tuple[int, int]
    raw: str


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_RE = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
             r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)")

_EN_DATE_DMY = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_RE})\.?,?\s+(\d{{4}})\b")
_EN_DATE_MDY = re.compile(
    rf"\b({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b")
_EN_DATE_SLASH = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_EN_DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")

_CJK_DIGIT = {"零": 0, "〇": 0, "○": 0, "一": 1, "二": 2, "兩": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}

_ZH_DATE = re.compile(
    r"([零〇○一二三四五六七八九]{4}|\d{4})年"
    r"([一二三四五六七八九十]{1,2}|\d{1,2})月"
    r"([一二三四五六七八九十]{1,3}|\d{1,2})日")


def _cjk_small(s: str) -> int | None:
    """Chinese numeral under 100 (e.g. 十二, 三十一) -> int."""
    if s.isdigit():
        return int(s)
    if not s:
        return None
    if "十" in s:
        tens_s, _, ones_s = s.partition("十")
        tens = _CJK_DIGIT.get(tens_s, 1) if tens_s else 1
        ones = _CJK_DIGIT.get(ones_s, 0) if ones_s else 0
        if (tens_s and tens_s not in _CJK_DIGIT) or (ones_s and ones_s not in _CJK_DIGIT):
            return None
        return tens * 10 + ones
    total = 0
    for ch in s:
        if ch not in _CJK_DIGIT:
            return None
        total = total * 10 + _CJK_DIGIT[ch]
    return total


def _iso(y: int, m: int, d: int) -> str | None:
    if not (1 <= m <= 12 and 1 <= d <= 31 and 1000 <= y <= 9999):
        return None
    return f"{y:04d}-{m:02d}-{d:02d}"


def extract_dates_en(text: str) -> list[Date]:
    out: list[Date] = []
    taken: list[tuple[int, int]] = []

    def add(iso: str | None, m: re.Match):
        if iso is None:
            return
        s, e = m.span()
        if any(s < te and e > ts for ts, te in taken):
            return
        taken.append((s, e))
        out.append(Date(iso, (s, e), m.group(0)))

    for m in _EN_DATE_DMY.finditer(text):
        mon = _MONTHS.get(m.group(2)[:3].lower()) or _MONTHS.get(m.group(2).lower())
        add(_iso(int(m.group(3)), mon or 0, int(m.group(1))), m)
    for m in _EN_DATE_MDY.finditer(text):
        mon = _MONTHS.get(m.group(1)[:3].lower()) or _MONTHS.get(m.group(1).lower())
        add(_iso(int(m.group(3)), mon or 0, int(m.group(2))), m)
    for m in _EN_DATE_SLASH.finditer(text):
        add(_iso(int(m.group(3)), int(m.group(2)), int(m.group(1))), m)
    for m in _EN_DATE_ISO.finditer(text):
        add(_iso(int(m.group(1)), int(m.group(2)), int(m.group(3))), m)
    out.sort(key=lambda d: d.span)
    return out


def extract_dates_zh(text: str) -> list[Date]:
    out: list[Date] = []
    for m in _ZH_DATE.finditer(text):
        y_s, m_s, d_s = m.group(1), m.group(2), m.group(3)
        if y_s.isdigit():
            y = int(y_s)
        else:
            y = 0
            for ch in y_s:
                y = y * 10 + _CJK_DIGIT[ch]
        mon, day = _cjk_small(m_s), _cjk_small(d_s)
        if mon is None or day is None:
            continue
        iso = _iso(y, mon, day)
        if iso:
            out.append(Date(iso, m.span(), m.group(0)))
    return out


# ---------------------------------------------------------------------------
# Currency
# ---------------------------------------------------------------------------

_EN_CUR = [
    # ISO codes are glued to digits in filings (RMB9,300,000, HKD1.2 million): no trailing \b
    ("HKD", re.compile(r"HK\$|\bHKD(?![A-Za-z])|\bHong\s+Kong\s+dollars?\b", re.I)),
    ("CNY", re.compile(r"\bRMB(?![A-Za-z])|\bCNY(?![A-Za-z])|\bRenminbi\b", re.I)),
    ("USD", re.compile(r"US\$|U\.S\.\$|\bUSD(?![A-Za-z])|\bU\.?S\.?\s+dollars?\b|\bUnited\s+States\s+dollars?\b", re.I)),
    ("CAD", re.compile(r"C\$|CA\$|\bCAD(?![A-Za-z])|\bCanadian\s+dollars?\b", re.I)),
    ("EUR", re.compile(r"€|\bEUR(?![A-Za-z])|\beuros?\b", re.I)),
    ("GBP", re.compile(r"£|\bGBP(?![A-Za-z])|\bpounds?\s+sterling\b|\bBritish\s+pounds?\b", re.I)),
]
_ZH_CUR = [
    ("HKD", re.compile(r"港幣|港元")),
    ("CNY", re.compile(r"人民幣|人民币")),
    ("USD", re.compile(r"美元|美金")),
    ("CAD", re.compile(r"加元|加幣")),
    ("EUR", re.compile(r"歐元|欧元")),
    ("GBP", re.compile(r"英鎊|英镑")),
]


def extract_currency(text: str, lang: str) -> list[Cur]:
    """lang: "en" / "zh" (today's tables) or any language code; other Latin languages share _LATIN_CUR."""
    if lang == "en":
        table = _EN_CUR
    elif lang == "zh":
        table = _ZH_CUR
    elif lang == "ja":
        table = _JA_CUR
    else:
        table = _LATIN_CUR
    out: list[Cur] = []
    for code, rx in table:
        for m in rx.finditer(text):
            out.append(Cur(code, m.span(), m.group(0)))
    out.sort(key=lambda c: c.span)
    return out


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------

_EN_MULT = {"thousand": 1e3, "k": 1e3, "million": 1e6, "mn": 1e6, "m": 1e6, "mm": 1e6,
            "billion": 1e9, "bn": 1e9, "b": 1e9, "trillion": 1e12}

_CUR_SYM = r"HK\$|US\$|U\.S\.\$|C\$|S\$|RMB|HKD|USD|CNY|EUR|GBP|CAD|\$|€|£"
_EN_NUM = re.compile(
    rf"(?:(?P<cur>{_CUR_SYM})\s?)?"
    r"(?P<open>\()?"
    rf"(?:(?P<cur2>{_CUR_SYM})\s?)?"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<close>\))?"
    r"(?P<pct>\s?(?:%|per\s?cent\b|percent\b))?"
    r"(?:\s?(?P<mult>million|billion|trillion|thousand|mn|bn|mm)\b)?",
    re.I,
)
_EN_ORDINAL = re.compile(r"^(st|nd|rd|th)\b", re.I)
_EN_REF_BEFORE = re.compile(
    r"(?:\b(?:Rules?|Chapter|Chapters|paragraphs?|paras?\.?|sections?|clauses?|notes?|"
    r"items?|appendix|appendices|page|pages|pp?\.|no\.|nos\.|tel|fax)\s*[:\s]?\s*$)", re.I)

_ZH_MULT = {"億": 1e8, "亿": 1e8, "萬": 1e4, "万": 1e4, "百萬": 1e6, "百万": 1e6, "千萬": 1e7, "千万": 1e7,
            "萬億": 1e12, "千": 1e3, "百": 1e2}
_ZH_NUM = re.compile(
    r"(?P<cur>港幣|港元|人民幣|人民币|美元|美金|加元|歐元|英鎊)?"
    r"(?P<open>[(（])?"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<close>[)）])?"
    r"(?P<mult>萬億|百萬|千萬|百万|千万|億|亿|萬|万|千)?"
    r"(?P<pct>%|％)?"
    r"(?P<unit>元|港元|美元|人民幣)?"
)
_ZH_PCT_CJK = re.compile(r"百分之(?P<num>[零一二兩三四五六七八九十點点]+|\d+(?:\.\d+)?)")
_ZH_CJK_NUM = re.compile(r"(?<![第])(?P<cur>港幣|港元|人民幣|美元)?(?P<num>[零一二兩两三四五六七八九十百千萬万億亿]{2,}[點点]?[零一二兩两三四五六七八九]*)(?P<unit>元|港元|美元|人民幣)?")
# common two-character words that start with a numeral and are not numbers
_ZH_NOT_NUM_AFTER = set("般切分定致旦律直樣同起再向些下併方面經概貫體系列旦帶路步日月年")
_ZH_NOT_NUM_WORDS = {"十分", "萬一", "一切", "一般", "一致", "統一", "唯一", "一旦", "一律", "一直", "一同",
                     "一起", "一再", "一向", "一些", "一下", "一併", "一方", "一經", "一概", "一貫", "一體",
                     "一系列", "一帶一路", "一步", "萬事", "千萬", "百般", "三方", "十足", "一定"}


def _f(s: str) -> float:
    return float(s.replace(",", ""))


def _cn_value(s: str) -> float | None:
    if cn2an is None:
        return None
    try:
        v = cn2an.cn2an(s, "smart")
        return float(v)
    except Exception:
        return None


def _masked(text: str, spans: list[tuple[int, int]]) -> str:
    """Replace the given spans with spaces so later regexes skip them (offsets preserved)."""
    if not spans:
        return text
    chars = list(text)
    for s, e in spans:
        for i in range(s, e):
            chars[i] = " "
    return "".join(chars)


def extract_numbers_en(text: str, date_spans: list[tuple[int, int]] | None = None) -> list[Num]:
    src = _masked(text, date_spans or [])
    out: list[Num] = []
    for m in _EN_NUM.finditer(src):
        s, e = m.span()
        num_s, num_e = m.span("num")
        after = src[num_e:num_e + 3]
        before = src[max(0, num_s - 24):num_s]
        # ordinals: 1st, 2nd, 3rd, 4th
        if _EN_ORDINAL.match(after):
            continue
        # clause / rule references: Rule 14.07(1), 14A.76, Chapter 14A, paragraph 2
        if re.match(r"[A-Za-z]", after) and not m.group("pct") and not m.group("mult"):
            continue
        if re.match(r"\(\d", src[num_e:num_e + 2]):
            continue
        if _EN_REF_BEFORE.search(before):
            continue
        # a decimal like 14.07 immediately preceded by a letter/digit-dot ref (e.g. "14A.76") -> skip
        if num_s > 0 and re.match(r"[A-Za-z0-9.]", src[num_s - 1]) and not (m.group("cur") or m.group("cur2")):
            continue
        # list markers "(1)" "(2)" : parenthesised 1-2 digit ints with no comma/decimal
        raw_num = m.group("num")
        if m.group("open") and m.group("close") and len(raw_num) <= 2 and "," not in raw_num and "." not in raw_num:
            continue
        # a bare "(" with no ")" is not a negative; trim it from the span
        if m.group("open") and not m.group("close"):
            s = m.start("cur2") if m.group("cur2") else num_s
        if m.group("close") and not m.group("open"):
            e = m.end("mult") if m.group("mult") else (m.end("pct") if m.group("pct") else num_e)
        value = _f(raw_num)
        kind = "plain"
        mult_word = None
        if m.group("pct"):
            kind = "pct"
        elif m.group("mult"):
            mult_word = m.group("mult").lower()
            value *= _EN_MULT.get(mult_word, 1)
            kind = "scaled"
        if m.group("open") and m.group("close"):
            value = -value
        out.append(Num(value, (s, e), text[s:e], kind, (m.group("cur") or m.group("cur2") or None), mult_word))
    return out


def extract_numbers_zh(text: str, date_spans: list[tuple[int, int]] | None = None) -> list[Num]:
    src = _masked(text, date_spans or [])
    out: list[Num] = []
    taken: list[tuple[int, int]] = []

    def free(s, e):
        return not any(s < te and e > ts for ts, te in taken)

    # 百分之六十 / 百分之60
    for m in _ZH_PCT_CJK.finditer(src):
        num = m.group("num")
        v = _f(num) if num.replace(".", "").isdigit() else _cn_value(num)
        if v is None:
            continue
        s, e = m.span()
        taken.append((s, e))
        out.append(Num(v, (s, e), text[s:e], "pct"))

    # Arabic digits with optional 萬/億 multiplier, currency prefix, 元 suffix
    for m in _ZH_NUM.finditer(src):
        _ns, _ne = m.span("num")
        if src[max(0, _ns - 1):_ns] == "第" or re.match(r"[A-Za-z]|[章條项項款節段]", src[_ne:_ne + 1] or "") \
                or re.match(r"[A-Za-z]?[章條项項款節段]", src[_ne:_ne + 2] or ""):
            continue
        s, e = m.span()
        if not free(s, e):
            continue
        num_s, num_e = m.span("num")
        # clause references: 第14.07(1)條, 14A.76
        if re.match(r"[A-Za-z]", src[num_e:num_e + 1]) or re.match(r"\(\d|（\d", src[num_e:num_e + 2]):
            continue
        if num_s > 0 and re.match(r"[A-Za-z0-9.]", src[num_s - 1]) and not (m.group("cur") or m.group("cur2")):
            continue
        # list markers "(1)" / "（1）" with no multiplier
        raw_num = m.group("num")
        neg = bool(m.group("open") and m.group("close"))
        if neg and len(raw_num) <= 2 and not m.group("mult") and not m.group("pct") and "," not in raw_num:
            continue
        if m.group("open") and not m.group("close"):
            s = num_s
        if m.group("close") and not m.group("open"):
            e = m.end("unit") if m.group("unit") else (m.end("pct") if m.group("pct") else
                                                       (m.end("mult") if m.group("mult") else num_e))
        value = _f(raw_num)
        kind = "plain"
        mult_word = None
        if m.group("pct"):
            kind = "pct"
        elif m.group("mult"):
            mult_word = m.group("mult")
            value *= _ZH_MULT.get(mult_word, 1)
            kind = "scaled"
        if neg:
            value = -value
        # keep the currency word / 元 inside the span (港幣1,210萬元) like the fixture
        taken.append((s, e))
        out.append(Num(value, (s, e), text[s:e], kind, (m.group("cur") or None), mult_word))

    # Full Chinese numerals: 六十, 一千二百萬 ... (2+ chars, not an ordinal, not a common word)
    for m in _ZH_CJK_NUM.finditer(src):
        s, e = m.span()
        if not free(s, e):
            continue
        num = m.group("num")
        if num in _ZH_NOT_NUM_WORDS:
            continue
        nxt = src[e:e + 1]
        if nxt and nxt in _ZH_NOT_NUM_AFTER and not m.group("unit"):
            continue
        v = _cn_value(num)
        if v is None:
            continue
        mult_word = None
        kind = "cjk"
        for mw in ("億", "萬"):
            if mw in num:
                mult_word = mw
        taken.append((s, e))
        out.append(Num(v, (s, e), text[s:e], kind, (m.group("cur") or None), mult_word))
    out.sort(key=lambda n: n.span)
    return out


# ---------------------------------------------------------------------------
# Latin-script locales other than English (fr, de, it, es, pt, nl)
# ---------------------------------------------------------------------------
# Grouping: space / narrow no-break space / no-break space / apostrophe (de-CH) / period (de, it, es, pt, nl).
# Decimal: comma (de-CH also uses a period, disambiguated per number). The EN/ZH code paths above are untouched.

_SP = "   "
_MONTHS_LOCALE = {
    "fr": {"janvier": 1, "janv": 1, "février": 2, "fevrier": 2, "févr": 2, "fév": 2, "mars": 3, "avril": 4, "avr": 4,
           "mai": 5, "juin": 6, "juillet": 7, "juil": 7, "août": 8, "aout": 8, "septembre": 9, "sept": 9,
           "octobre": 10, "oct": 10, "novembre": 11, "nov": 11, "décembre": 12, "decembre": 12, "déc": 12, "dec": 12},
    "de": {"januar": 1, "jänner": 1, "jan": 1, "februar": 2, "feb": 2, "märz": 3, "maerz": 3, "mär": 3, "april": 4,
           "apr": 4, "mai": 5, "juni": 6, "jun": 6, "juli": 7, "jul": 7, "august": 8, "aug": 8, "september": 9,
           "sept": 9, "sep": 9, "oktober": 10, "okt": 10, "november": 11, "nov": 11, "dezember": 12, "dez": 12},
    "it": {"gennaio": 1, "gen": 1, "febbraio": 2, "feb": 2, "marzo": 3, "mar": 3, "aprile": 4, "apr": 4,
           "maggio": 5, "mag": 5, "giugno": 6, "giu": 6, "luglio": 7, "lug": 7, "agosto": 8, "ago": 8,
           "settembre": 9, "set": 9, "sett": 9, "ottobre": 10, "ott": 10, "novembre": 11, "nov": 11,
           "dicembre": 12, "dic": 12},
    "es": {"enero": 1, "ene": 1, "febrero": 2, "feb": 2, "marzo": 3, "mar": 3, "abril": 4, "abr": 4, "mayo": 5,
           "junio": 6, "jun": 6, "julio": 7, "jul": 7, "agosto": 8, "ago": 8, "septiembre": 9, "setiembre": 9,
           "sept": 9, "sep": 9, "octubre": 10, "oct": 10, "noviembre": 11, "nov": 11, "diciembre": 12, "dic": 12},
    "pt": {"janeiro": 1, "jan": 1, "fevereiro": 2, "fev": 2, "março": 3, "marco": 3, "mar": 3, "abril": 4, "abr": 4,
           "maio": 5, "mai": 5, "junho": 6, "jun": 6, "julho": 7, "jul": 7, "agosto": 8, "ago": 8, "setembro": 9,
           "set": 9, "outubro": 10, "out": 10, "novembro": 11, "nov": 11, "dezembro": 12, "dez": 12},
    "nl": {"januari": 1, "jan": 1, "februari": 2, "feb": 2, "maart": 3, "mrt": 3, "april": 4, "apr": 4, "mei": 5,
           "juni": 6, "jun": 6, "juli": 7, "jul": 7, "augustus": 8, "aug": 8, "september": 9, "sep": 9,
           "sept": 9, "oktober": 10, "okt": 10, "november": 11, "nov": 11, "december": 12, "dec": 12},
}
# scale words -> (multiplier, canonical EN word used by _fmt_value)
_SCALE_LOCALE = {
    "fr": {"mille": 1e3, "milliers": 1e3, "million": 1e6, "millions": 1e6, "mio": 1e6, "mn": 1e6,
           "milliard": 1e9, "milliards": 1e9, "mrd": 1e9, "mds": 1e9},
    "de": {"tausend": 1e3, "tsd": 1e3, "million": 1e6, "millionen": 1e6, "mio": 1e6, "mill": 1e6,
           "milliarde": 1e9, "milliarden": 1e9, "mrd": 1e9},
    "it": {"mila": 1e3, "milione": 1e6, "milioni": 1e6, "mln": 1e6, "mio": 1e6, "miliardo": 1e9, "miliardi": 1e9, "mld": 1e9},
    "es": {"mil": 1e3, "millón": 1e6, "millon": 1e6, "millones": 1e6, "mm": 1e6,
           "miles de millones": 1e9, "mil millones": 1e9, "millardo": 1e9, "millardos": 1e9},
    "pt": {"mil": 1e3, "milhão": 1e6, "milhao": 1e6, "milhões": 1e6, "milhoes": 1e6,
           "mil milhões": 1e9, "mil milhoes": 1e9, "bilhão": 1e9, "bilhao": 1e9, "bilhões": 1e9, "bilhoes": 1e9},
    "nl": {"duizend": 1e3, "miljoen": 1e6, "mln": 1e6, "miljard": 1e9, "mld": 1e9},
}
_PCT_LOCALE = {"fr": r"pour\s?cent", "de": r"prozent", "it": r"per\s?cento", "es": r"por\s?ciento",
               "pt": r"por\s?cento", "nl": r"procent"}
_LATIN_CUR_SYM = r"HK\$|US\$|U\.S\.\$|C\$|CA\$|S\$|RMB|HKD|USD|CNY|EUR|GBP|CAD|CHF|\$|€|£"
_LATIN_CUR = [
    ("HKD", re.compile(r"HK\$|\bHKD(?![A-Za-z])|\bHong\s+Kong\s+dollars?\b|\bdollars?\s+de\s+Hong\s+Kong\b|\bHongkong-Dollar", re.I)),
    ("CNY", re.compile(r"\bRMB(?![A-Za-z])|\bCNY(?![A-Za-z])|\bRenminbi\b|\byuans?\b", re.I)),
    ("USD", re.compile(r"US\$|U\.S\.\$|\bUSD(?![A-Za-z])|\bU\.?S\.?\s+dollars?\b|\bUnited\s+States\s+dollars?\b|"
                       r"\bdollars?\s+(?:américains?|americains?|US)\b|\bUS-Dollar|\bd[óo]lares\s+(?:estadounidenses|americanos)\b|"
                       r"\bdollari\s+(?:statunitensi|americani)\b", re.I)),
    ("CAD", re.compile(r"C\$|CA\$|\bCAD(?![A-Za-z])|\bCanadian\s+dollars?\b|\bdollars?\s+canadiens?\b|"
                       r"\bkanadische[nrs]?\s+Dollar|\bdollari\s+canadesi\b|\bd[óo]lares\s+canadienses\b", re.I)),
    ("EUR", re.compile(r"€|\bEUR(?![A-Za-z])|\beuros?\b|\bEuro\b", re.I)),
    ("CHF", re.compile(r"\bCHF(?![A-Za-z])|\bfrancs?\s+suisses?\b|\bSchweizer\s+Franken\b|\bFranken\b|"
                       r"\bfranchi\s+svizzeri\b|\bfrancos\s+suizos\b|\bSwiss\s+francs?\b", re.I)),
    ("GBP", re.compile(r"£|\bGBP(?![A-Za-z])|\bpounds?\s+sterling\b|\bBritish\s+pounds?\b|\blivres?\s+sterling\b|"
                       r"\bPfund\s+Sterling\b|\bsterline\b|\blibras\s+esterlinas\b", re.I)),
]
_JA_CUR = [("JPY", re.compile(r"円|¥")), ("USD", re.compile(r"米ドル")), ("EUR", re.compile(r"ユーロ")),
           ("HKD", re.compile(r"香港ドル")), ("CNY", re.compile(r"人民元")), ("GBP", re.compile(r"英ポンド"))]
_LOCALE_REF_BEFORE = re.compile(
    r"(?:\b(?:article|art\.?|articles|paragraphe|alin[ée]a|page|pages|section|chapitre|note|"
    r"Artikel|Art\.?|Absatz|Abs\.?|Seite|Kapitel|Ziffer|Ziff\.?|Randnr\.?|"
    r"articolo|articoli|pagina|capitolo|comma|"
    r"art[íi]culo|art[íi]culos|p[áa]gina|cap[íi]tulo|apartado|"
    r"artigo|artigos|cap[íi]tulo|"
    r"artikel|pagina|hoofdstuk|lid|"
    r"no\.?|n[°º]|nr\.?|tel|fax)\s*[:\s]?\s*$)", re.I)


def _canon_scale(mult: float) -> str:
    return {1e3: "thousand", 1e6: "million", 1e9: "billion"}.get(mult, "million")


def _locale_regexes(code: str):
    months = _MONTHS_LOCALE[code]
    m_alt = "|".join(re.escape(m) for m in sorted(months, key=len, reverse=True))
    date_named = re.compile(
        rf"\b(\d{{1,2}})(?:er|re|e|º|ª|°|\.)?[{_SP}]+(?:de[{_SP}]+|d')?({m_alt})\.?[{_SP}]+(?:de[{_SP}]+)?(\d{{4}})\b", re.I)
    scale = _SCALE_LOCALE[code]
    s_alt = "|".join(re.escape(w).replace(r"\ ", r"\s+") for w in sorted(scale, key=len, reverse=True))
    num = re.compile(
        rf"(?:(?P<cur>{_LATIN_CUR_SYM})[{_SP}]?)?"
        r"(?P<open>\()?"
        rf"(?P<num>\d{{1,3}}(?:[{_SP}'.,]\d{{3}})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
        r"(?P<close>\))?"
        rf"(?P<pct>[{_SP}]?(?:%|{_PCT_LOCALE[code]}))?"
        rf"(?:[{_SP}]?(?P<mult>{s_alt})\.?(?![a-zà-öø-ÿ]))?",
        re.I,
    )
    return date_named, num, scale


_LOCALE_CACHE: dict[str, tuple] = {}


def _locale(code: str):
    if code not in _LOCALE_CACHE:
        _LOCALE_CACHE[code] = _locale_regexes(code)
    return _LOCALE_CACHE[code]


_DATE_DOTTED = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
_DATE_DASHED = re.compile(r"\b(\d{1,2})-(\d{1,2})-(\d{4})\b")


def extract_dates_locale(text: str, code: str) -> list[Date]:
    """Named-month, day-first numeric (24/09/2026, 24.09.2026, 24-09-2026) and ISO dates."""
    date_named, _, _ = _locale(code)
    months = _MONTHS_LOCALE[code]
    out: list[Date] = []
    taken: list[tuple[int, int]] = []

    def add(iso: str | None, m: re.Match):
        if iso is None:
            return
        s, e = m.span()
        if any(s < te and e > ts for ts, te in taken):
            return
        taken.append((s, e))
        out.append(Date(iso, (s, e), m.group(0)))

    for m in date_named.finditer(text):
        add(_iso(int(m.group(3)), months.get(m.group(2).lower(), 0), int(m.group(1))), m)
    for rx in (_EN_DATE_SLASH, _DATE_DOTTED, _DATE_DASHED):
        for m in rx.finditer(text):
            add(_iso(int(m.group(3)), int(m.group(2)), int(m.group(1))), m)
    for m in _EN_DATE_ISO.finditer(text):
        add(_iso(int(m.group(1)), int(m.group(2)), int(m.group(3))), m)
    out.sort(key=lambda d: d.span)
    return out


def _parse_locale_number(raw: str, has_scale: bool) -> float | None:
    """'1 234 567,89' / '1.234.567,89' / '1'234'567.89' / '12,1' / '2.500' -> float, comma-decimal rules."""
    s = re.sub(rf"[{_SP}']", "", raw)
    commas, dots = s.count(","), s.count(".")
    if commas and dots:
        if s.rfind(",") > s.rfind("."):          # 1.234.567,89
            s = s.replace(".", "").replace(",", ".")
        else:                                    # 1,234,567.89 (English-style, copied over)
            s = s.replace(",", "")
    elif commas:
        parts = s.split(",")
        if commas >= 2 and all(len(p) == 3 for p in parts[1:]):
            s = s.replace(",", "")               # 12,400,000
        elif commas == 1 and len(parts[1]) == 3 and not has_scale:
            s = s.replace(",", "")               # 1,234 actions -> grouping; 1,250 milliard -> decimal
        else:
            s = s.replace(",", ".")
    elif dots:
        parts = s.split(".")
        if all(len(p) == 3 for p in parts[1:]) and len(parts[0]) <= 3:
            s = s.replace(".", "")               # 2.500 / 1.234.567 / 1.200 millones -> grouping
    try:
        return float(s)
    except ValueError:
        return None


def extract_numbers_locale(text: str, code: str, date_spans: list[tuple[int, int]] | None = None) -> list[Num]:
    _, num_re, scale = _locale(code)
    src = _masked(text, date_spans or [])
    out: list[Num] = []
    for m in num_re.finditer(src):
        s, e = m.span()
        num_s, num_e = m.span("num")
        after = src[num_e:num_e + 3]
        before = src[max(0, num_s - 24):num_s]
        if re.match(r"[A-Za-zà-öø-ÿ]", after) and not m.group("pct") and not m.group("mult"):
            continue                              # 1er, 2e, 3º, 12h, A1 references
        if re.match(r"\(\d", src[num_e:num_e + 2]):
            continue
        if _LOCALE_REF_BEFORE.search(before):
            continue
        if num_s > 0 and re.match(r"[A-Za-z0-9.]", src[num_s - 1]) and not m.group("cur"):
            continue
        raw_num = m.group("num")
        if m.group("open") and m.group("close") and len(raw_num) <= 2 and not re.search(r"[.,]", raw_num):
            continue                              # list markers (1) (2)
        if m.group("open") and not m.group("close"):
            s = num_s
        if m.group("close") and not m.group("open"):
            e = m.end("mult") if m.group("mult") else (m.end("pct") if m.group("pct") else num_e)
        mult_word = None
        mult = 1.0
        if m.group("mult"):
            key = re.sub(r"\s+", " ", m.group("mult").lower())
            mult = scale.get(key, 1.0)
        value = _parse_locale_number(raw_num, mult != 1.0)
        if value is None:
            continue
        kind = "plain"
        if m.group("pct"):
            kind = "pct"
        elif m.group("mult"):
            mult_word = _canon_scale(mult)
            value *= mult
            kind = "scaled"
        if m.group("open") and m.group("close"):
            value = -value
        out.append(Num(value, (s, e), text[s:e], kind, (m.group("cur") or None), mult_word))
    return out


# ---------------------------------------------------------------------------
# Dispatch by language code ("en" / "zh" keep today's behaviour exactly)
# ---------------------------------------------------------------------------

def extract_dates(text: str, code: str = "en") -> list[Date]:
    if code in ("zh", "ja"):
        return extract_dates_zh(text)
    if code in _MONTHS_LOCALE:
        return extract_dates_locale(text, code)
    return extract_dates_en(text)


def extract_numbers(text: str, code: str = "en", date_spans: list[tuple[int, int]] | None = None) -> list[Num]:
    if code in ("zh", "ja"):
        return extract_numbers_zh(text, date_spans)
    if code in _SCALE_LOCALE:
        return extract_numbers_locale(text, code, date_spans)
    return extract_numbers_en(text, date_spans)


# ---------------------------------------------------------------------------
# Comparison helpers
# ---------------------------------------------------------------------------

def _same(a: float, b: float) -> bool:
    if a == b:
        return True
    return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-9)


def _fmt_value(v: float, like: Num | None, cur: str | None) -> str:
    """Render a numeric value the way the EN side wrote its number (HK$12.1 million / 60% / 48,200,000)."""
    prefix = ""
    if cur:
        prefix = {"HKD": "HK$", "USD": "US$", "CNY": "RMB", "CAD": "C$", "EUR": "€", "GBP": "£", "CHF": "CHF ",
                  "JPY": "¥"}.get(cur, cur)
    if like is not None and like.kind == "pct":
        return f"{_trim(v)}%"
    mult = like.mult_word if like is not None else None
    if mult in ("billion", "bn", "b") or (mult == "億" and abs(v) >= 1e9):
        return f"{prefix}{_trim(v / 1e9)} billion"
    if mult in ("million", "mn", "m", "mm", "百萬") or (mult in ("萬", "億") and abs(v) >= 1e6):
        return f"{prefix}{_trim(v / 1e6)} million"
    if abs(v) >= 1000 and float(v).is_integer():
        return f"{prefix}{int(v):,}"
    return f"{prefix}{_trim(v)}"


def _trim(v: float) -> str:
    if float(v).is_integer():
        return f"{int(v):,}" if abs(v) >= 1000 else str(int(v))
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return s


_CUR_CODE = {"HK$": "HKD", "HKD": "HKD", "US$": "USD", "U.S.$": "USD", "USD": "USD", "RMB": "CNY", "CNY": "CNY",
             "C$": "CAD", "CA$": "CAD", "CAD": "CAD", "€": "EUR", "EUR": "EUR", "£": "GBP", "GBP": "GBP", "CHF": "CHF",
             "港幣": "HKD", "港元": "HKD", "人民幣": "CNY", "人民币": "CNY", "美元": "USD", "美金": "USD",
             "加元": "CAD", "歐元": "EUR", "英鎊": "GBP"}


def _cur_of(nums: list[Num], curs: list[Cur]) -> str | None:
    for n in nums:
        if n.currency and n.currency.upper() in _CUR_CODE:
            return _CUR_CODE[n.currency.upper()]
        if n.currency and n.currency in _CUR_CODE:
            return _CUR_CODE[n.currency]
    return curs[0].code if curs else None


def _is_yearish(n: Num) -> bool:
    return n.kind == "plain" and float(n.value).is_integer() and 1900 <= n.value <= 2100 and "," not in n.raw


def _fmt_date(iso: str) -> str:
    y, m, d = iso.split("-")
    names = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
             "October", "November", "December"]
    return f"{int(d)} {names[int(m) - 1]} {y}"


# ---------------------------------------------------------------------------
# Pair-level check
# ---------------------------------------------------------------------------

def check_pair(en_text: str, zh_text: str, code_a: str = "en", code_b: str = "zh",
               names: tuple[str, str] = ("English", "Chinese")) -> list[dict]:
    """Return partial findings (type, en_span, zh_span, explanation) for one aligned pair.

    en_text / zh_text are the two SLOTS; code_a / code_b are the language codes inside them and
    names are the language names used in explanations."""
    found: list[dict] = []
    name_a, name_b = names

    en_dates = extract_dates(en_text, code_a)
    zh_dates = extract_dates(zh_text, code_b)
    en_nums = extract_numbers(en_text, code_a, [d.span for d in en_dates])
    zh_nums = extract_numbers(zh_text, code_b, [d.span for d in zh_dates])
    en_cur = extract_currency(en_text, code_a)
    zh_cur = extract_currency(zh_text, code_b)

    # ---- numbers ----------------------------------------------------------
    used_zh: set[int] = set()
    unmatched_en: list[Num] = []
    for a in en_nums:
        hit = None
        for j, b in enumerate(zh_nums):
            if j in used_zh:
                continue
            if _same(a.value, b.value):
                hit = j
                break
        if hit is None:
            unmatched_en.append(a)
            continue
        used_zh.add(hit)
        b = zh_nums[hit]
        # same value, different notation (plain digits vs scaled word) -> FORMAT
        # plain digits vs 萬/億 notation is the normal HK bilingual convention — not a finding.
    unmatched_zh = [b for j, b in enumerate(zh_nums) if j not in used_zh]

    # stock-code / year-looking integers that both sides carry are already matched above; a stray
    # year on one side only is almost always a date fragment, so drop those rather than flag them.
    unmatched_en = [n for n in unmatched_en if not _is_yearish(n)]
    unmatched_zh = [n for n in unmatched_zh if not _is_yearish(n)]
    # a bare digit string that appears verbatim on the other side (Chapter 14 / 第14章) is a reference
    def _digits(n): return re.sub(r"[^\d.]", "", n.raw or "")
    unmatched_en = [n for n in unmatched_en if not (_digits(n) and _digits(n) in zh_text and n.kind == "plain")]
    unmatched_zh = [n for n in unmatched_zh if not (_digits(n) and _digits(n) in en_text and n.kind == "plain")]

    cur_code = _cur_of(en_nums, en_cur) or _cur_of(zh_nums, zh_cur)
    while unmatched_en or unmatched_zh:
        if unmatched_en and unmatched_zh:
            a = unmatched_en.pop(0)
            # nearest ZH figure by log-ratio (12.4m vs 12.1m rather than 12.4m vs 60)
            def dist(b: Num) -> float:
                if a.value == 0 or b.value == 0 or (a.value > 0) != (b.value > 0):
                    return abs(a.value - b.value) + 1e12
                return abs(math.log(abs(a.value)) - math.log(abs(b.value)))
            b = min(unmatched_zh, key=dist)
            unmatched_zh.remove(b)
            a_cur = cur_code if (a.currency or a.kind != "pct") else None
            a_txt = _fmt_value(a.value, a, a_cur if a.currency else None)
            b_txt = _fmt_value(b.value, a if a.kind in ("pct", "scaled") else b, a_cur if (a.currency or b.currency) else None)
            found.append({
                "type": "NUMBER_MISMATCH",
                "en_span": list(a.span), "zh_span": list(b.span),
                "explanation": f"{name_a} states {a_txt}; {name_b} states {b_txt}.",
            })
        elif unmatched_en:
            a = unmatched_en.pop(0)
            found.append({
                "type": "NUMBER_MISMATCH",
                "en_span": list(a.span), "zh_span": None,
                "explanation": f"{name_a} states {a.raw.strip()}; {name_b} has no corresponding figure.",
            })
        else:
            b = unmatched_zh.pop(0)
            found.append({
                "type": "NUMBER_MISMATCH",
                "en_span": None, "zh_span": list(b.span),
                "explanation": f"{name_b} states {b.raw.strip()}; {name_a} has no corresponding figure.",
            })

    # ---- dates ------------------------------------------------------------
    label = "long stop date" if re.search(r"long\s+stop\s+date|date\s+butoir|date\s+limite|Stichtag|"
                                          r"data\s+limite|fecha\s+l[íi]mite", en_text + " " + zh_text, re.I) else "date"
    used_zh_d: set[int] = set()
    un_en: list[Date] = []
    for a in en_dates:
        hit = next((j for j, b in enumerate(zh_dates) if j not in used_zh_d and a.iso == b.iso), None)
        if hit is None:
            un_en.append(a)
        else:
            used_zh_d.add(hit)
    un_zh = [b for j, b in enumerate(zh_dates) if j not in used_zh_d]
    while un_en or un_zh:
        if un_en and un_zh:
            a = un_en.pop(0)
            b = min(un_zh, key=lambda d: abs(int(d.iso.replace("-", "")) - int(a.iso.replace("-", ""))))
            un_zh.remove(b)
            found.append({
                "type": "DATE_MISMATCH",
                "en_span": list(a.span), "zh_span": list(b.span),
                "explanation": f"{name_a} {label} is {_fmt_date(a.iso)}; {name_b} is {_fmt_date(b.iso)}.",
            })
        elif un_en:
            a = un_en.pop(0)
            found.append({
                "type": "DATE_MISMATCH", "en_span": list(a.span), "zh_span": None,
                "explanation": f"{name_a} states {_fmt_date(a.iso)}; {name_b} has no corresponding date.",
            })
        else:
            b = un_zh.pop(0)
            found.append({
                "type": "DATE_MISMATCH", "en_span": None, "zh_span": list(b.span),
                "explanation": f"{name_b} states {_fmt_date(b.iso)}; {name_a} has no corresponding date.",
            })

    # ---- currency ---------------------------------------------------------
    en_codes = {c.code for c in en_cur}
    zh_codes = {c.code for c in zh_cur}
    if en_codes and zh_codes and en_codes != zh_codes:
        only_en = [c for c in en_cur if c.code not in zh_codes]
        only_zh = [c for c in zh_cur if c.code not in en_codes]
        found.append({
            "type": "CURRENCY_MISMATCH",
            "en_span": list(only_en[0].span) if only_en else list(en_cur[0].span),
            "zh_span": list(only_zh[0].span) if only_zh else list(zh_cur[0].span),
            "explanation": (f"{name_a} uses {', '.join(sorted(en_codes))}; "
                            f"{name_b} uses {', '.join(sorted(zh_codes))}."),
        })
    return found


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _join(ids: list[str], idx: dict, sep: str = " ") -> tuple[str, int | None]:
    texts, page = [], None
    for sid in ids:
        rec = idx.get(sid)
        if not rec:
            continue
        t = (rec.get("text") or "").strip()
        if t:
            texts.append(t)
        if page is None and rec.get("page") is not None:
            page = rec.get("page")
    return sep.join(texts), page


def _slot_languages(languages: dict | None) -> dict:
    out = {}
    for slot in ("en", "zh"):
        lang = (languages or {}).get(slot) or DEFAULT_LANGUAGES[slot]
        out[slot] = {"code": lang.get("code") or "und", "name": lang.get("name") or "Unknown",
                     "script": lang.get("script") or "Zyyy"}
    return out


def run_checks(alignment: dict, idx_en: dict, idx_zh: dict, languages: dict | None = None) -> list[dict]:
    L = _slot_languages(languages)
    code_a, code_b = L["en"]["code"], L["zh"]["code"]
    names = (short_name(L["en"], "English"), short_name(L["zh"], "Chinese"))
    sep_a, sep_b = joiner(L["en"]), joiner(L["zh"])
    findings: list[dict] = []
    for sec in alignment.get("sections", []) or []:
        section = sec.get("en_heading") or sec.get("zh_heading") or ""
        for pair in sec.get("pairs", []) or []:
            en_text, en_page = _join(pair.get("en_ids", []), idx_en, sep_a)
            zh_text, zh_page = _join(pair.get("zh_ids", []), idx_zh, sep_b)
            if not en_text or not zh_text:
                continue
            for f in check_pair(en_text, zh_text, code_a, code_b, names):
                findings.append({
                    "type": f["type"],
                    "source": "deterministic",
                    "pair_id": pair.get("id"),
                    "section": section,
                    "en": {"page": en_page, "text": en_text, "span": f["en_span"]},
                    "zh": {"page": zh_page, "text": zh_text, "span": f["zh_span"]},
                    "explanation": f["explanation"],
                    "confidence": 1.0,
                })
    return findings


if __name__ == "__main__":  # quick manual probe
    import json
    import sys
    en = sys.argv[1] if len(sys.argv) > 2 else "The Consideration is HK$12.4 million, payable in cash on Completion."
    zh = sys.argv[2] if len(sys.argv) > 2 else "代價為港幣1,210萬元，於完成時以現金支付。"
    print(json.dumps(check_pair(en, zh), ensure_ascii=False, indent=1))
