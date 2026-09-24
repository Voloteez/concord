"""Batched LLM pairwise judgments + omission pass (see CONTRACT.md, PRD "LLM prompts and API usage").

run_semantic(alignment, idx_en, idx_zh, glossary, authoritative, run_dir, on_progress) -> list[dict]
  finding dicts WITHOUT severity/status, source "llm":
  {type, source:"llm", pair_id | sentence_id, section, en:{page,text,span}, zh:{page,text,span},
   explanation, confidence}

Pass 1: llm.FAST triage on every pair (batches of 10, 6 threads).
Pass 2: llm.STRONG re-check of every non-EQUIVALENT pair; the STRONG verdict wins.
Pass 3: llm.STRONG omission judgment per section that has unaligned sentences.
All calls go through llm.call_json with cache_key = sha256(prompt) so demo replays are instant.
"""
from __future__ import annotations

import hashlib
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import llm

log = logging.getLogger("concord.semantic")

BATCH_SIZE = 10
CONCURRENCY = 6

VERDICTS = ["EQUIVALENT", "HEDGE_CHANGE", "MEANING_SHIFT", "SCOPE_CHANGE", "PARTIAL_OMISSION", "WORDING"]
VERDICT_TO_TYPE = {
    "HEDGE_CHANGE": "HEDGE_CHANGE",
    "MEANING_SHIFT": "MEANING_SHIFT",
    "SCOPE_CHANGE": "SCOPE_CHANGE",
    "PARTIAL_OMISSION": "OMISSION_MINOR",
    "WORDING": "WORDING",
}

# --- PRD system prompt (verbatim) -------------------------------------------------------------
SYSTEM_PROMPT = """You are a bilingual disclosure reviewer for a listed company. You compare aligned passages
from the English and Chinese versions of the same regulatory filing and report only
differences in meaning. You never comment on style.

Rules:
- Treat the glossary as authoritative for defined terms. "the Company" and 本公司 are equivalent;
  "the Group" and 本集團 are equivalent; the Company and the Group are NOT equivalent.
- Report HEDGE_CHANGE when modality differs: may / could / 可能 vs will / shall / 將 / 須;
  expects / intends / 預期 / 擬 vs confirms / guarantees / 確認 / 保證.
- Report SCOPE_CHANGE when a quantifier differs: some / certain / 若干 vs all / 所有; or when
  a condition, exception or qualifier is present in one passage only.
- Report PARTIAL_OMISSION when a clause with substantive content is missing from one side.
- Report MEANING_SHIFT for any other difference that would change what a reasonable investor understands.
- Report WORDING only when the passages are equivalent in meaning but you are less than
  90% confident; otherwise EQUIVALENT.
- Numbers and dates are checked separately; do not report them.
- en_span and zh_span must be exact substrings of the passages given. If the issue is an
  omission, the span on the side that has the content is set and the other is null.
- Return JSON matching the schema and nothing else."""

# PRD PairJudgment / BatchJudgment as a JSON tool schema
BATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "judgments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "pair_id": {"type": "string"},
                    "verdict": {"type": "string", "enum": VERDICTS},
                    "en_span": {"type": ["string", "null"],
                                "description": "exact substring of the English passage"},
                    "zh_span": {"type": ["string", "null"],
                                "description": "exact substring of the Chinese passage"},
                    "explanation": {"type": "string", "description": "one sentence, under 30 words"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["pair_id", "verdict", "en_span", "zh_span", "explanation", "confidence"],
            },
        }
    },
    "required": ["judgments"],
}

OMISSION_SYSTEM_PROMPT = """You are a bilingual disclosure reviewer for a listed company. You are given one section of a
regulatory filing in English and in Chinese, plus a list of sentences that could not be paired
with a sentence on the other side.

For each unpaired sentence decide whether its content is present anywhere in the other language
(for example merged into a neighbouring sentence, or split across two) or genuinely absent.
- present_elsewhere: true if the meaning is carried by some passage on the other side; quote that
  passage exactly in matched_text (an exact substring of the other side), else matched_text is null.
- material: true if the sentence contains a number, a date, a modal verb (may / will / shall / must /
  可能 / 將 / 須 / 應), a defined term from the glossary, a condition, or a risk statement.
- reason: one sentence, under 30 words, written for a reviewer.
- confidence: 0 to 1.
Treat the glossary as authoritative for defined terms. Return JSON matching the schema and nothing else."""

OMISSION_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sentence_id": {"type": "string"},
                    "present_elsewhere": {"type": "boolean"},
                    "matched_text": {"type": ["string", "null"]},
                    "material": {"type": "boolean"},
                    "reason": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["sentence_id", "present_elsewhere", "matched_text", "material", "reason"],
            },
        }
    },
    "required": ["results"],
}


# ---------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------

def _sid_num(sid: str) -> int:
    m = re.search(r"(\d+)$", sid or "")
    return int(m.group(1)) if m else 0


def _join(ids: list[str], idx: dict, lang: str) -> tuple[str, int | None]:
    texts, page = [], None
    for sid in ids or []:
        rec = idx.get(sid)
        if not rec:
            continue
        t = (rec.get("text") or "").strip()
        if t:
            texts.append(t)
        if page is None and rec.get("page") is not None:
            page = rec.get("page")
    return (" " if lang == "en" else "").join(texts), page


def find_span(text: str, needle: str | None) -> list[int] | None:
    """Exact substring -> [start, end]; else whitespace-insensitive; else None."""
    if not needle or not text:
        return None
    i = text.find(needle)
    if i >= 0:
        return [i, i + len(needle)]
    stripped = needle.strip()
    if stripped and stripped != needle:
        i = text.find(stripped)
        if i >= 0:
            return [i, i + len(stripped)]
    chars = [ch for ch in needle if not ch.isspace()]
    if not chars:
        return None
    pattern = r"\s*".join(re.escape(ch) for ch in chars)
    m = re.search(pattern, text)
    if m:
        return [m.start(), m.end()]
    # last resort: case-insensitive for Latin text
    m = re.search(pattern, text, re.I)
    if m:
        return [m.start(), m.end()]
    return None


def _cache_key(system: str, user: str) -> str:
    return hashlib.sha256((system + "\n\n" + user).encode("utf-8")).hexdigest()


def _glossary_block(glossary: list[dict]) -> str:
    lines = [f"{g.get('en', '')} = {g.get('zh', '')}" for g in (glossary or []) if g.get("en") or g.get("zh")]
    return "\n".join(lines) if lines else "(none)"


def _pair_records(alignment: dict, idx_en: dict, idx_zh: dict) -> list[dict]:
    """Flatten alignment into one record per pair with its section and neighbours."""
    records: list[dict] = []
    for sec in alignment.get("sections", []) or []:
        sec_records: list[dict] = []
        for pair in sec.get("pairs", []) or []:
            en_text, en_page = _join(pair.get("en_ids", []), idx_en, "en")
            zh_text, zh_page = _join(pair.get("zh_ids", []), idx_zh, "zh")
            if not en_text and not zh_text:
                continue
            sec_records.append({
                "pair_id": pair.get("id"),
                "section_id": sec.get("id"),
                "section_en": sec.get("en_heading") or "",
                "section_zh": sec.get("zh_heading") or "",
                "section": sec.get("en_heading") or sec.get("zh_heading") or "",
                "en_text": en_text, "zh_text": zh_text,
                "en_page": en_page, "zh_page": zh_page,
                "prev": None, "next": None,
            })
        for i, rec in enumerate(sec_records):
            rec["prev"] = sec_records[i - 1] if i > 0 else None
            rec["next"] = sec_records[i + 1] if i + 1 < len(sec_records) else None
        records.extend(sec_records)
    return records


def _build_user(authoritative: str, glossary: list[dict], batch: list[dict]) -> str:
    """PRD user message template."""
    first, last = batch[0], batch[-1]
    auth = authoritative if authoritative in ("EN", "ZH") else "none"
    lines = [f"Authoritative version: {auth}", "", "Glossary:", _glossary_block(glossary), "",
             f"Section: {first['section_en']} / {first['section_zh']}", ""]
    prev = first.get("prev")
    lines += ["Context before:",
              f"EN: {prev['en_text'] if prev else '(start of section)'}",
              f"ZH: {prev['zh_text'] if prev else '(start of section)'}", ""]
    lines.append("Pairs to judge:")
    for rec in batch:
        lines += [f"[{rec['pair_id']}]", f"EN: {rec['en_text']}", f"ZH: {rec['zh_text']}", ""]
    nxt = last.get("next")
    lines += ["Context after:",
              f"EN: {nxt['en_text'] if nxt else '(end of section)'}",
              f"ZH: {nxt['zh_text'] if nxt else '(end of section)'}"]
    return "\n".join(lines)


def _batches(records: list[dict], size: int = BATCH_SIZE) -> list[list[dict]]:
    """Batches of up to `size` pairs, never crossing a section (the template has one Section line)."""
    out: list[list[dict]] = []
    cur: list[dict] = []
    cur_sec = None
    for rec in records:
        if cur and (rec["section_id"] != cur_sec or len(cur) >= size):
            out.append(cur)
            cur = []
        cur.append(rec)
        cur_sec = rec["section_id"]
    if cur:
        out.append(cur)
    return out


def _judge_batch(batch: list[dict], model: str, authoritative: str, glossary: list[dict],
                 run_dir: str | None) -> dict[str, dict]:
    user = _build_user(authoritative, glossary, batch)
    try:
        res = llm.call_json(system=SYSTEM_PROMPT, user=user, schema=BATCH_SCHEMA, model=model,
                            cache_key=_cache_key(SYSTEM_PROMPT, user), run_dir=run_dir)
    except Exception as e:  # one bad batch must not sink the run
        log.warning("semantic batch failed (%s): %s", model, e)
        return {}
    out: dict[str, dict] = {}
    for j in (res or {}).get("judgments", []) or []:
        if isinstance(j, dict) and j.get("pair_id"):
            out[str(j["pair_id"])] = j
    return out


def _run_pass(records: list[dict], model: str, authoritative: str, glossary: list[dict],
              run_dir: str | None, on_progress, label: str) -> dict[str, dict]:
    batches = _batches(records)
    total = len(records)
    done = 0
    verdicts: dict[str, dict] = {}
    if not batches:
        return verdicts
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        futs = {ex.submit(_judge_batch, b, model, authoritative, glossary, run_dir): b for b in batches}
        for fut in as_completed(futs):
            b = futs[fut]
            try:
                verdicts.update(fut.result())
            except Exception as e:  # pragma: no cover
                log.warning("semantic batch raised: %s", e)
            done += len(b)
            if on_progress:
                try:
                    on_progress(label.format(done=done, total=total))
                except Exception:
                    pass
    return verdicts


def _clamp(v, default: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, f))


def _pair_finding(rec: dict, j: dict) -> dict | None:
    verdict = j.get("verdict")
    ftype = VERDICT_TO_TYPE.get(verdict)
    if not ftype:
        return None
    en_needle, zh_needle = j.get("en_span"), j.get("zh_span")
    en_span = find_span(rec["en_text"], en_needle)
    zh_span = find_span(rec["zh_text"], zh_needle)
    hallucinated = (en_needle and en_span is None) or (zh_needle and zh_span is None)
    if hallucinated:
        if verdict == "WORDING":
            log.info("dropping WORDING on %s: span not found (%r / %r)", rec["pair_id"], en_needle, zh_needle)
            return None
        log.info("span not found on %s (%s): en=%r zh=%r; keeping with null span",
                 rec["pair_id"], verdict, en_needle, zh_needle)
    return {
        "type": ftype,
        "source": "llm",
        "pair_id": rec["pair_id"],
        "section": rec["section"],
        "en": {"page": rec["en_page"], "text": rec["en_text"], "span": en_span},
        "zh": {"page": rec["zh_page"], "text": rec["zh_text"], "span": zh_span},
        "explanation": (j.get("explanation") or "").strip() or f"{verdict.replace('_', ' ').title()} between the two versions.",
        "confidence": _clamp(j.get("confidence"), 0.75),
    }


# ---------------------------------------------------------------------------------------------
# omission pass
# ---------------------------------------------------------------------------------------------

def _section_ids(sec: dict, unaligned: list[dict], lang: str) -> list[str]:
    ids: set[str] = set()
    key = f"{lang}_ids"
    for pair in sec.get("pairs", []) or []:
        ids.update(pair.get(key, []) or [])
    for u in unaligned:
        if u.get("lang") == lang and u.get("section_id") == sec.get("id"):
            ids.add(u["id"])
    return sorted(ids, key=_sid_num)


def _neighbour_text(sec: dict, sid: str, lang: str, own_ids: list[str], idx_other: dict) -> tuple[str, int | None]:
    """Nearest neighbouring sentence on the OTHER side of the section, by order."""
    other = "zh" if lang == "en" else "en"
    own_key, other_key = f"{lang}_ids", f"{other}_ids"
    pos = {s: i for i, s in enumerate(own_ids)}
    me = pos.get(sid, 0)
    best, best_d = None, None
    for pair in sec.get("pairs", []) or []:
        oids = pair.get(other_key) or []
        if not oids:
            continue
        for s in pair.get(own_key) or []:
            d = abs(pos.get(s, 0) - me)
            if best_d is None or d < best_d:
                best, best_d = oids, d
    if best:
        text, page = _join(best, idx_other, other)
        if text:
            return text, page
    # fall back to the first sentence on the other side
    for pair in sec.get("pairs", []) or []:
        text, page = _join(pair.get(other_key) or [], idx_other, other)
        if text:
            return text, page
    return "", None


def _full_text(idx: dict, cap: int = 16000) -> str:
    parts = [(v.get("text") or "") for _, v in sorted(idx.items(), key=lambda kv: _sid_num(kv[0]))]
    out = "\n".join(t for t in parts if t)
    return out[:cap]


def _omission_user(sec: dict, authoritative: str, glossary: list[dict], en_ids: list[str], zh_ids: list[str],
                   idx_en: dict, idx_zh: dict, unpaired: list[dict]) -> str:
    auth = authoritative if authoritative in ("EN", "ZH") else "none"
    lines = [f"Authoritative version: {auth}", "", "Glossary:", _glossary_block(glossary), "",
             f"Section: {sec.get('en_heading') or ''} / {sec.get('zh_heading') or ''}", "",
             "English section:"]
    lines += [f"[{sid}] {(idx_en.get(sid) or {}).get('text', '')}" for sid in en_ids]
    lines += ["", "Chinese section:"]
    lines += [f"[{sid}] {(idx_zh.get(sid) or {}).get('text', '')}" for sid in zh_ids]
    # content often moves across headings (signature blocks, director lists, boilerplate), so the
    # judge also sees the whole other-side document, not just this section
    langs = {u["lang"] for u in unpaired}
    if "en" in langs:
        lines += ["", "Full Chinese document (search here before calling anything absent):", _full_text(idx_zh)]
    if "zh" in langs:
        lines += ["", "Full English document (search here before calling anything absent):", _full_text(idx_en)]
    lines += ["", "Unpaired sentences to judge:"]
    for u in unpaired:
        idx = idx_en if u["lang"] == "en" else idx_zh
        lines.append(f"[{u['id']}] ({u['lang'].upper()}) {(idx.get(u['id']) or {}).get('text', '')}")
    return "\n".join(lines)


def _run_omissions(alignment: dict, idx_en: dict, idx_zh: dict, glossary: list[dict], authoritative: str,
                   run_dir: str | None, on_progress) -> list[dict]:
    unaligned = [u for u in (alignment.get("unaligned_sentences") or []) if u.get("id")]
    if not unaligned:
        return []
    by_sec: dict[str, list[dict]] = {}
    for u in unaligned:
        by_sec.setdefault(u.get("section_id") or "", []).append(u)
    sections = {s.get("id"): s for s in alignment.get("sections", []) or []}
    findings: list[dict] = []
    total = len(unaligned)
    done = 0

    def one(sec_id: str, items: list[dict]) -> list[dict]:
        sec = sections.get(sec_id) or {"id": sec_id, "pairs": [], "en_heading": "", "zh_heading": ""}
        en_ids = _section_ids(sec, items, "en")
        zh_ids = _section_ids(sec, items, "zh")
        # skip ids we have no text for
        items_ok = [u for u in items if (idx_en if u["lang"] == "en" else idx_zh).get(u["id"])]
        if not items_ok:
            return []
        user = _omission_user(sec, authoritative, glossary, en_ids, zh_ids, idx_en, idx_zh, items_ok)
        try:
            res = llm.call_json(system=OMISSION_SYSTEM_PROMPT, user=user, schema=OMISSION_SCHEMA,
                                model=llm.STRONG, cache_key=_cache_key(OMISSION_SYSTEM_PROMPT, user),
                                run_dir=run_dir)
        except Exception as e:
            log.warning("omission call failed for %s: %s", sec_id, e)
            return []
        by_id = {str(r.get("sentence_id")): r for r in (res or {}).get("results", []) or [] if isinstance(r, dict)}
        out: list[dict] = []
        section = sec.get("en_heading") or sec.get("zh_heading") or ""
        for u in items_ok:
            r = by_id.get(u["id"])
            if not r or r.get("present_elsewhere"):
                continue
            lang = u["lang"]
            idx_own = idx_en if lang == "en" else idx_zh
            idx_other = idx_zh if lang == "en" else idx_en
            own = idx_own[u["id"]]
            own_text = (own.get("text") or "").strip()
            own_ids = en_ids if lang == "en" else zh_ids
            other_text, other_page = _neighbour_text(sec, u["id"], lang, own_ids, idx_other)
            material = bool(r.get("material"))
            side_own = {"page": own.get("page"), "text": own_text, "span": [0, len(own_text)] if own_text else None}
            side_other = {"page": other_page if other_page is not None else own.get("page"),
                          "text": other_text, "span": None}
            out.append({
                "type": "OMISSION_MATERIAL" if material else "OMISSION_MINOR",
                "source": "llm",
                "sentence_id": u["id"],
                "section": section,
                "en": side_own if lang == "en" else side_other,
                "zh": side_own if lang == "zh" else side_other,
                "explanation": (r.get("reason") or "").strip() or "Sentence has no counterpart in the other version.",
                "confidence": _clamp(r.get("confidence"), 0.9 if material else 0.7),
            })
        return out

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        futs = {ex.submit(one, sid, items): items for sid, items in by_sec.items()}
        for fut in as_completed(futs):
            try:
                findings.extend(fut.result())
            except Exception as e:  # pragma: no cover
                log.warning("omission section raised: %s", e)
            done += len(futs[fut])
            if on_progress:
                try:
                    on_progress(f"Checking unpaired sentences {done}/{total}")
                except Exception:
                    pass
    return findings


# ---------------------------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------------------------

def run_semantic(alignment: dict, idx_en: dict, idx_zh: dict, glossary: list,
                 authoritative: str, run_dir: str, on_progress) -> list[dict]:
    records = _pair_records(alignment, idx_en, idx_zh)
    by_id = {r["pair_id"]: r for r in records}

    # pass 1: cheap triage on everything
    triage = _run_pass(records, llm.FAST, authoritative, glossary, run_dir, on_progress,
                       "Analysing {done}/{total} pairs")
    flagged_ids = [pid for pid, j in triage.items() if j.get("verdict") != "EQUIVALENT" and pid in by_id]
    flagged = [by_id[pid] for pid in records_order(records, flagged_ids)]

    # pass 2: strong model re-checks anything not marked equivalent; its verdict wins
    final: dict[str, dict] = {}
    if flagged:
        strong = _run_pass(flagged, llm.STRONG, authoritative, glossary, run_dir, on_progress,
                           "Re-checking {done}/{total} flagged pairs")
        for pid in flagged_ids:
            j = strong.get(pid)
            if j is None:            # strong call failed for this batch -> fall back to triage
                j = triage.get(pid)
            final[pid] = j

    findings: list[dict] = []
    for pid, j in final.items():
        if not j or j.get("verdict") == "EQUIVALENT":
            continue
        f = _pair_finding(by_id[pid], j)
        if f:
            findings.append(f)

    # pass 3: omissions for unaligned sentences
    findings.extend(_run_omissions(alignment, idx_en, idx_zh, glossary, authoritative, run_dir, on_progress))
    return findings


def records_order(records: list[dict], ids: list[str]) -> list[str]:
    wanted = set(ids)
    return [r["pair_id"] for r in records if r["pair_id"] in wanted]
