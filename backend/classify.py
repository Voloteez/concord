"""Type -> severity, escalation, dedupe, rank, summary counts (see CONTRACT.md).

classify(det, llm, alignment, glossary, authoritative) -> (findings, counts)
recount(findings, unaligned_sections) -> counts

The LLM never sets severity; this module owns the map.
"""
from __future__ import annotations

import copy
import re

SEVERITY = {
    "NUMBER_MISMATCH": "Critical",
    "DATE_MISMATCH": "Critical",
    "CURRENCY_MISMATCH": "Critical",
    "OMISSION_MATERIAL": "Critical",
    "HEDGE_CHANGE": "Material",
    "MEANING_SHIFT": "Material",
    "SCOPE_CHANGE": "Material",
    "OMISSION_MINOR": "Cosmetic",
    "WORDING": "Cosmetic",
    "FORMAT": "Cosmetic",
}
_SEV_RANK = {"Critical": 0, "Material": 1, "Cosmetic": 2}

_MODAL_EN = re.compile(r"\b(may|will|shall|must)\b", re.I)
_MODAL_ZH = re.compile(r"可能|將|須|應")
_NUMBER = re.compile(r"\d|[一二兩三四五六七八九十百千]+(?:萬|億|元|股|%|％|個|名|項)|百分之")
_DATE = re.compile(
    r"\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?,?\s+\d{4}"
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}"
    r"|[零〇一二三四五六七八九\d]{4}年[一二三四五六七八九十\d]{1,2}月[一二三四五六七八九十\d]{1,3}日", re.I)
_RISK_HEADING = re.compile(r"risk|warning|condition|風險|警告|條件", re.I)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _span_text(side: dict | None) -> str:
    if not side:
        return ""
    text = side.get("text") or ""
    span = side.get("span")
    if span and isinstance(span, (list, tuple)) and len(span) == 2:
        try:
            return text[int(span[0]):int(span[1])]
        except (TypeError, ValueError):
            return text
    return ""


def _escalation_text(f: dict) -> tuple[str, str]:
    """The omitted sentence: spanned substring where a span exists, else the whole side text."""
    en_s, zh_s = _span_text(f.get("en")), _span_text(f.get("zh"))
    if en_s or zh_s:
        return en_s, zh_s
    return (f.get("en") or {}).get("text") or "", (f.get("zh") or {}).get("text") or ""


def _has_glossary_term(en: str, zh: str, glossary: list[dict]) -> bool:
    en_l = en.lower()
    for g in glossary or []:
        t_en = (g.get("en") or "").strip()
        t_zh = (g.get("zh") or "").strip()
        if t_en and len(t_en) > 2 and t_en.lower() in en_l:
            return True
        if t_zh and len(t_zh) > 1 and t_zh in zh:
            return True
    return False


def _should_escalate_omission(f: dict, glossary: list[dict]) -> bool:
    en, zh = _escalation_text(f)
    blob = en + " " + zh
    if _NUMBER.search(blob) or _DATE.search(blob):
        return True
    if _MODAL_EN.search(en) or _MODAL_ZH.search(zh):
        return True
    return _has_glossary_term(en, zh, glossary)


def _section_headings(f: dict, alignment: dict) -> str:
    """EN + ZH heading of the finding's section, so 風險 in a ZH-only heading still counts."""
    sec_name = f.get("section") or ""
    parts = [sec_name]
    for sec in (alignment or {}).get("sections", []) or []:
        if sec.get("en_heading") == sec_name or sec.get("zh_heading") == sec_name:
            parts += [sec.get("en_heading") or "", sec.get("zh_heading") or ""]
            break
    return " ".join(parts)


def _page(f: dict) -> int:
    p = (f.get("en") or {}).get("page")
    if p is None:
        p = (f.get("zh") or {}).get("page")
    try:
        return int(p)
    except (TypeError, ValueError):
        return 10 ** 6


def _key(f: dict) -> str:
    return str(f.get("pair_id") or f.get("sentence_id") or "")


def _fingerprint(f: dict) -> tuple:
    return (f.get("type"), _key(f), tuple((f.get("en") or {}).get("span") or ()),
            tuple((f.get("zh") or {}).get("span") or ()))


def _word_omission(f: dict, authoritative: str) -> None:
    """PRD: content missing from the non-authoritative side is worded 'omitted from Chinese'."""
    if f.get("type") not in ("OMISSION_MATERIAL", "OMISSION_MINOR"):
        return
    expl = (f.get("explanation") or "").strip()
    zh_null = (f.get("zh") or {}).get("span") is None
    en_null = (f.get("en") or {}).get("span") is None
    phrase = None
    if authoritative == "EN" and zh_null and not en_null:
        phrase = "omitted from Chinese"
    elif authoritative == "ZH" and en_null and not zh_null:
        phrase = "omitted from English"
    if phrase and phrase.lower() not in expl.lower():
        lang = phrase.split()[-1]
        # "is missing from the Chinese version" -> "is omitted from Chinese" rather than appending a second phrase
        rewritten, n = re.subn(
            rf"\b(missing|absent|not present|omitted)\s+(?:entirely\s+)?from\s+(?:the\s+)?{lang}(?:\s+(?:version|text|section|side))?(\s+entirely)?",
            phrase, expl, count=1, flags=re.I)
        if n:
            expl = rewritten if rewritten.endswith((".", "。")) else rewritten + "."
        else:
            expl = (expl.rstrip(" .;") + " — " + phrase + ".") if expl else phrase.capitalize() + "."
    f["explanation"] = expl


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def classify(det: list[dict], llm: list[dict], alignment: dict, glossary: list,
             authoritative: str) -> tuple[list[dict], dict]:
    det = [copy.deepcopy(f) for f in (det or [])]
    llm = [copy.deepcopy(f) for f in (llm or [])]

    # --- dedupe -----------------------------------------------------------------------------
    seen: set[tuple] = set()
    kept: list[dict] = []
    for f in det:
        fp = _fingerprint(f)
        if fp in seen:
            continue
        seen.add(fp)
        kept.append(f)
    det_pairs = {_key(f) for f in kept if f.get("pair_id")}
    llm_seen: set[tuple] = set()
    for f in llm:
        k = _key(f)
        # same pair flagged by both sources -> keep deterministic, drop llm
        if f.get("pair_id") and k in det_pairs:
            continue
        fp = (f.get("type"), k)
        if fp in llm_seen:
            continue
        llm_seen.add(fp)
        kept.append(f)

    # --- severity + escalations -------------------------------------------------------------
    for f in kept:
        ftype = f.get("type") or "WORDING"
        if ftype == "OMISSION_MINOR" and _should_escalate_omission(f, glossary):
            f["type"] = ftype = "OMISSION_MATERIAL"
        sev = SEVERITY.get(ftype, "Cosmetic")
        if ftype == "HEDGE_CHANGE" and _RISK_HEADING.search(_section_headings(f, alignment)):
            sev = "Critical"
        f["severity"] = sev
        _word_omission(f, authoritative)

    # --- rank: severity desc, page asc, then stable by pair/sentence id ---------------------
    kept.sort(key=lambda f: (_SEV_RANK.get(f.get("severity"), 3), _page(f), _key(f), f.get("type") or ""))

    # --- ids + review fields ----------------------------------------------------------------
    out: list[dict] = []
    for n, f in enumerate(kept, 1):
        g = {"id": f"f_{n:03d}", "type": f["type"], "severity": f["severity"],
             "source": f.get("source") or "llm", "section": f.get("section") or ""}
        if f.get("pair_id"):
            g["pair_id"] = f["pair_id"]
        if f.get("sentence_id"):
            g["sentence_id"] = f["sentence_id"]
        g["en"] = {"page": (f.get("en") or {}).get("page"), "text": (f.get("en") or {}).get("text") or "",
                   "span": (f.get("en") or {}).get("span")}
        g["zh"] = {"page": (f.get("zh") or {}).get("page"), "text": (f.get("zh") or {}).get("text") or "",
                   "span": (f.get("zh") or {}).get("span")}
        g["explanation"] = f.get("explanation") or ""
        try:
            g["confidence"] = round(float(f.get("confidence", 1.0)), 2)
        except (TypeError, ValueError):
            g["confidence"] = 1.0
        g["status"] = f.get("status") or "unreviewed"
        g["dismiss_reason"] = f.get("dismiss_reason")
        g["note"] = f.get("note")
        out.append(g)

    counts = recount(out, (alignment or {}).get("unaligned_sections") or [])
    return out, counts


def recount(findings: list[dict], unaligned_sections: list) -> dict:
    c = {"critical": 0, "material": 0, "cosmetic": 0}
    reviewed = 0
    for f in findings or []:
        sev = (f.get("severity") or "").lower()
        if sev in c:
            c[sev] += 1
        if (f.get("status") or "unreviewed") != "unreviewed":
            reviewed += 1
    c["unaligned_sections"] = len(unaligned_sections or [])
    c["reviewed"] = reviewed
    c["total"] = len(findings or [])
    return c
