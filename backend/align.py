"""LLM alignment: meta detection, glossary, sections then sentence pairs. See CONTRACT.md."""
from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from extract import DEFAULT_LANGUAGES
from llm import FAST, call_json

# ---------------------------------------------------------------- helpers

def _languages(blocks_en: dict, blocks_zh: dict, languages: dict | None) -> dict:
    """Detected language per SLOT: the argument wins, then blocks[...]["language"], then English/Chinese."""
    out = {}
    for slot, blocks in (("en", blocks_en), ("zh", blocks_zh)):
        lang = (languages or {}).get(slot) or (blocks or {}).get("language") or DEFAULT_LANGUAGES[slot]
        out[slot] = {"code": lang.get("code") or "und", "name": lang.get("name") or "Unknown",
                     "script": lang.get("script") or "Zyyy"}
    return out


def _names(languages: dict) -> tuple[str, str]:
    return languages["en"]["name"], languages["zh"]["name"]


def languages_is_cjk(blocks_zh: dict, languages: dict | None) -> bool:
    lang = (languages or {}).get("zh") or (blocks_zh or {}).get("language") or DEFAULT_LANGUAGES["zh"]
    return lang.get("script") in ("Hani", "Hant", "Hans", "Jpan")


def _h(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _sid_num(sid: str) -> int:
    m = re.search(r"(\d+)$", sid)
    return int(m.group(1)) if m else 0


def _headings(blocks: dict) -> list[tuple[int, dict]]:
    return [(i, b) for i, b in enumerate(blocks["blocks"]) if b.get("is_heading")]


def _section_sentences(blocks: dict, start: int, end: int | None) -> list[dict]:
    """Sentences (with page) in blocks[start:end]."""
    out = []
    for b in blocks["blocks"][start:end]:
        if b.get("is_heading"):
            continue
        for s in b.get("sentences", []):
            out.append({"id": s["id"], "text": s["text"], "page": b["page"]})
    return out


# ---------------------------------------------------------------- detect_meta

# Prevail clauses in each language. Every pattern captures the language MENTIONED; _MENTION maps that
# mention to a language code and detect_meta maps the code to whichever SLOT holds that language.
_MENTION_EN = r"English|Chinese|French|German|Italian|Spanish|Portuguese|Dutch|Japanese|Korean"
_MENTION_FR = r"anglaise|chinoise|française|francaise|allemande|italienne|espagnole|portugaise|néerlandaise|japonaise|coréenne"
_MENTION_DE = r"englische|chinesische|französische|deutsche|italienische|spanische|portugiesische|niederländische|japanische|koreanische"
_MENTION_IT = r"inglese|cinese|francese|tedesca|italiana|spagnola|portoghese|olandese|giapponese|coreana"
_MENTION_ES = r"inglesa|china|francesa|alemana|italiana|española|espanola|portuguesa|neerlandesa|japonesa|coreana"
_MENTION_ZH = r"英文|中文|法文|德文|意大利文|義大利文|西班牙文|葡萄牙文|荷蘭文|荷兰文|日文|韓文|韩文"
_MENTION_JA = r"英語|中国語|フランス語|ドイツ語|イタリア語|スペイン語|ポルトガル語|オランダ語|日本語|韓国語"
PREVAIL_PATTERNS = [
    re.compile(rf"\b({_MENTION_EN})\b[^.]{{0,80}}?\b(?:shall|will|to)\s+(?:prevail|govern|control)", re.I),
    re.compile(rf"\b({_MENTION_EN})\b[^.]{{0,80}}?\b(?:shall|will)\s+be\s+(?:authoritative|binding)", re.I),
    re.compile(rf"prevail[^.]{{0,40}}?\b({_MENTION_EN})\b", re.I),
    re.compile(rf"以({_MENTION_ZH})(?:版本|本|文本|版)?[為为]準?准?"),
    re.compile(rf"(?:version|texte)\s+({_MENTION_FR})[^.]{{0,80}}?(?:prévau|prevau|fait\s+foi|l'emport|fera\s+foi)", re.I),
    re.compile(rf"(?:die\s+)?({_MENTION_DE})\s+(?:Fassung|Version|Sprachfassung)[^.]{{0,60}}?"
               rf"(?:maßgeblich|massgeblich|maßgebend|verbindlich|Vorrang)", re.I),
    re.compile(rf"gilt\s+die\s+({_MENTION_DE})\s+(?:Fassung|Version|Sprachfassung)", re.I),
    re.compile(rf"prevale\s+la\s+versione\s+({_MENTION_IT})|versione\s+({_MENTION_IT})\s+(?:prevale|prevarrà|fa\s+fede)", re.I),
    re.compile(rf"prevalecer[áa]?\s+la\s+versi[óo]n\s+({_MENTION_ES})|versi[óo]n\s+({_MENTION_ES})\s+prevalecer[áa]?", re.I),
    re.compile(rf"prevalece(?:rá)?\s+a\s+vers[ãa]o\s+({_MENTION_ES})|vers[ãa]o\s+({_MENTION_ES})\s+prevalece(?:rá)?", re.I),
    re.compile(rf"({_MENTION_JA})版が優先"),
]
_MENTION_CODE = {
    "en": "english anglaise englische inglese inglesa 英文 英語",
    "zh": "chinese chinoise chinesische cinese china 中文 中国語",
    "fr": "french française francaise französische francese francesa 法文 フランス語",
    "de": "german allemande deutsche tedesca alemana 德文 ドイツ語",
    "it": "italian italienne italienische italiana 意大利文 義大利文 イタリア語",
    "es": "spanish espagnole spanische spagnola española espanola 西班牙文 スペイン語",
    "pt": "portuguese portugaise portugiesische portoghese portuguesa 葡萄牙文 ポルトガル語",
    "nl": "dutch néerlandaise niederländische olandese neerlandesa 荷蘭文 荷兰文 オランダ語",
    "ja": "japanese japonaise japanische giapponese japonesa 日文 日本語",
    "ko": "korean coréenne koreanische coreana 韓文 韩文 韓国語",
}
_MENTION = {m: code for code, ms in _MENTION_CODE.items() for m in ms.split()}


def _find_prevail_code(blocks_en: dict, blocks_zh: dict) -> str | None:
    """Language code named by a prevail clause on either side, or None if no clause was found."""
    for blocks in (blocks_en, blocks_zh):
        for b in blocks["blocks"]:
            t = b["text"]
            for rx in PREVAIL_PATTERNS:
                m = rx.search(t)
                if m:
                    mention = next((g for g in m.groups() if g), "")
                    return _MENTION.get(mention.lower(), "und")
    return None


def _slot_for(code: str, languages: dict) -> str:
    """Which SLOT holds the named language: "EN" / "ZH" (slot names) or "none"."""
    for slot, key in (("en", "EN"), ("zh", "ZH")):
        if languages[slot]["code"] == code:
            return key
    return "none"


def _first_pages_text(blocks: dict, max_pages: int = 2, max_chars: int = 3500) -> str:
    parts = []
    n = 0
    for b in blocks["blocks"]:
        if b["page"] > max_pages:
            break
        line = ("# " if b.get("is_heading") else "") + b["text"]
        parts.append(line)
        n += len(line)
        if n > max_chars:
            break
    return "\n".join(parts)


def detect_meta(blocks_en: dict, blocks_zh: dict, run_dir: str, languages: dict | None = None) -> dict:
    """authoritative is a SLOT ("EN" = slot en, "ZH" = slot zh, or "none"); the frontend maps slots to names."""
    languages = _languages(blocks_en, blocks_zh, languages)
    name_a, name_b = _names(languages)
    code = _find_prevail_code(blocks_en, blocks_zh)
    authoritative = _slot_for(code, languages) if code else "none"
    detected = code is not None
    en_txt = _first_pages_text(blocks_en)
    zh_txt = _first_pages_text(blocks_zh)
    schema = {
        "type": "object",
        "properties": {
            "en_title": {"type": "string", "description": f"Full document title (announcement headline) in {name_a}."},
            "zh_title": {"type": "string", "description": f"Full document title in {name_b}."},
            "company": {"type": "string", "description": "Issuer / company name, in English where the document gives one."},
            "stock_code": {"type": "string", "description": "Stock code / ticker digits only, or empty string."},
        },
        "required": ["en_title", "zh_title", "company", "stock_code"],
    }
    meta = {"en_title": "", "zh_title": "", "company": "", "stock_code": ""}
    try:
        out = call_json(
            system="You extract document metadata from the opening pages of a bilingual regulatory filing "
                   f"({name_a} and {name_b} versions). Return exact strings from the text; do not invent.",
            user=f"{name_a.upper()} (first pages):\n{en_txt}\n\n{name_b.upper()} (first pages):\n{zh_txt}",
            schema=schema, model=FAST, cache_key=_h("meta", en_txt, zh_txt), run_dir=run_dir,
        )
        for k in meta:
            v = out.get(k)
            meta[k] = v.strip() if isinstance(v, str) else ""
    except Exception as e:  # meta is non-fatal
        print(f"[align] detect_meta LLM failed: {e}")
    if not meta["en_title"]:
        hs = _headings(blocks_en)
        meta["en_title"] = hs[0][1]["text"] if hs else ""
    if not meta["zh_title"]:
        hs = _headings(blocks_zh)
        meta["zh_title"] = hs[0][1]["text"] if hs else ""
    meta["authoritative"] = authoritative
    meta["authoritative_detected"] = detected
    return meta


# ---------------------------------------------------------------- glossary

# "Term" means / « Terme » désigne / „Begriff" bezeichnet / "Termine" indica / 「詞語」指 / “词语”指 / 「用語」とは
TERM_PATTERNS = [
    re.compile(r"[\"“]([^\"”]{1,60})[\"”]\s+(?:means|shall mean|has the meaning)", re.I),
    re.compile(r"«\s*([^»]{1,60}?)\s*»\s+(?:désigne|designe|signifie|s'entend|a le sens)", re.I),
    re.compile(r"[„\"“]([^\"“”]{1,60})[\"“”]\s+(?:bezeichnet|bedeutet|meint|hat die Bedeutung)", re.I),
    re.compile(r"[\"“«]([^\"”»]{1,60})[\"”»]\s+(?:indica|significa|designa|si intende|se refiere|se entiende|refere-se|betekent)", re.I),
    re.compile(r"「([^」]{1,30})」\s*(?:指|乃指|即|的意思是|是指|とは)"),
    re.compile(r"“([^”]{1,30})”\s*(?:指|乃指|即|是指)"),
]
DEFINITION_HEADINGS = ("DEFINITIONS", "DEFINITION", "INTERPRETATION", "釋義", "释义", "定義", "定义", "詞彙", "词汇",
                       "DÉFINITIONS", "DEFINITIONEN", "BEGRIFFSBESTIMMUNGEN", "DEFINIZIONI", "DEFINICIONES",
                       "DEFINIÇÕES", "DEFINITIES", "用語の定義")


def _definitions_text(blocks: dict, keys: tuple[str, ...] = DEFINITION_HEADINGS) -> str:
    hs = _headings(blocks)
    for n, (i, b) in enumerate(hs):
        if any(k in b["text"].upper() for k in keys):
            end = hs[n + 1][0] if n + 1 < len(hs) else None
            return "\n".join(x["text"] for x in blocks["blocks"][i + 1:end])
    return "\n".join(x["text"] for x in blocks["blocks"])


def _terms(text: str) -> list[str]:
    found: list[str] = []
    for rx in TERM_PATTERNS:
        found += rx.findall(text)
    return _dedupe(found)


def _dedupe(seq: list[str]) -> list[str]:
    seen, out = set(), []
    for s in seq:
        s = s.strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def extract_glossary(blocks_en: dict, blocks_zh: dict, run_dir: str, languages: dict | None = None) -> list[dict]:
    """[{"en": term in slot en, "zh": term in slot zh}] — keys are slots, not languages."""
    languages = _languages(blocks_en, blocks_zh, languages)
    name_a, name_b = _names(languages)
    en_terms = _terms(_definitions_text(blocks_en))[:40]
    zh_terms = _terms(_definitions_text(blocks_zh))[:40]
    if not en_terms or not zh_terms:
        return []
    schema = {
        "type": "object",
        "properties": {
            "pairs": {"type": "array", "items": {"type": "object", "properties": {
                "en_idx": {"type": "integer"}, "zh_idx": {"type": "integer"}},
                "required": ["en_idx", "zh_idx"]}},
        },
        "required": ["pairs"],
    }
    en_list = "\n".join(f"{i}: {t}" for i, t in enumerate(en_terms))
    zh_list = "\n".join(f"{i}: {t}" for i, t in enumerate(zh_terms))
    pairs: list[dict] = []
    try:
        out = call_json(
            system=f"You align defined terms between the {name_a} and {name_b} versions of the same legal document. "
                   f"Pair each {name_a} term with the {name_b} term that translates it. Lists are usually in the same "
                   "order but may differ. Each index appears at most once. Omit terms with no counterpart.",
            user=f"{name_a.upper()} TERMS:\n{en_list}\n\n{name_b.upper()} TERMS:\n{zh_list}",
            schema=schema, model=FAST, cache_key=_h("glossary", en_list, zh_list), run_dir=run_dir,
        )
        used_en, used_zh = set(), set()
        for p in out.get("pairs", []):
            try:
                ei, zi = int(p["en_idx"]), int(p["zh_idx"])
            except Exception:
                continue
            if 0 <= ei < len(en_terms) and 0 <= zi < len(zh_terms) and ei not in used_en and zi not in used_zh:
                used_en.add(ei); used_zh.add(zi)
                pairs.append({"en": en_terms[ei], "zh": zh_terms[zi]})
    except Exception as e:
        print(f"[align] glossary LLM failed: {e}")
    if not pairs and len(en_terms) == len(zh_terms):
        pairs = [{"en": e, "zh": z} for e, z in zip(en_terms, zh_terms)]
    return pairs[:40]


# ---------------------------------------------------------------- align

SECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "matches": {"type": "array", "items": {"type": "object", "properties": {
            "en_idx": {"type": "integer"}, "zh_idx": {"type": "integer"},
            "score": {"type": "number", "description": "0-1 confidence that these headings denote the same section"}},
            "required": ["en_idx", "zh_idx", "score"]}},
        "unmatched_en": {"type": "array", "items": {"type": "integer"}},
        "unmatched_zh": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["matches", "unmatched_en", "unmatched_zh"],
}

PAIR_SCHEMA = {
    "type": "object",
    "properties": {
        "pairs": {"type": "array", "items": {"type": "object", "properties": {
            "en_ids": {"type": "array", "items": {"type": "string"}},
            "zh_ids": {"type": "array", "items": {"type": "string"}},
            "score": {"type": "number", "description": "0-1 confidence the two sides express the same content"}},
            "required": ["en_ids", "zh_ids", "score"]}},
        "unpaired_en": {"type": "array", "items": {"type": "string"}},
        "unpaired_zh": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["pairs", "unpaired_en", "unpaired_zh"],
}


def _clamp(x, default=0.5) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except Exception:
        return default


def _align_sections(h_en: list[dict], h_zh: list[dict], run_dir: str,
                    names: tuple[str, str] = ("English", "Chinese")) -> tuple[list[tuple[int, int, float]], list[int], list[int]]:
    """Returns (matches[(en_i, zh_i, score)], unmatched_en, unmatched_zh) as indexes into h_en/h_zh."""
    if not h_en or not h_zh:
        return [], list(range(len(h_en))), list(range(len(h_zh)))
    name_a, name_b = names
    en_list = "\n".join(f"{i}: {h['text']}" for i, h in enumerate(h_en))
    zh_list = "\n".join(f"{i}: {h['text']}" for i, h in enumerate(h_zh))
    out = call_json(
        system=f"You align section headings between the {name_a} and {name_b} versions of the same regulatory filing. "
               f"Match each {name_a} heading to the {name_b} heading that translates it (same section, not merely similar "
               "topic). Headings are in document order and usually correspond one-to-one in order, but a section may be "
               "missing, added, split, or reordered on one side. Each index may appear in at most one match. "
               "List every unmatched index on each side. Score is your confidence (0-1).",
        user=f"{name_a.upper()} HEADINGS:\n{en_list}\n\n{name_b.upper()} HEADINGS:\n{zh_list}",
        schema=SECTION_SCHEMA, model=FAST, cache_key=_h("sections", en_list, zh_list), run_dir=run_dir,
    )
    used_en, used_zh, matches = set(), set(), []
    for m in out.get("matches", []):
        try:
            ei, zi = int(m["en_idx"]), int(m["zh_idx"])
        except Exception:
            continue
        if 0 <= ei < len(h_en) and 0 <= zi < len(h_zh) and ei not in used_en and zi not in used_zh:
            used_en.add(ei); used_zh.add(zi)
            matches.append((ei, zi, _clamp(m.get("score"), 0.7)))
    matches.sort()
    un_en = [i for i in range(len(h_en)) if i not in used_en]
    un_zh = [i for i in range(len(h_zh)) if i not in used_zh]
    return matches, un_en, un_zh


def _align_pairs(sec_id: str, en_sents: list[dict], zh_sents: list[dict], run_dir: str,
                 names: tuple[str, str] = ("English", "Chinese")) -> dict:
    en_ids = {s["id"] for s in en_sents}
    zh_ids = {s["id"] for s in zh_sents}
    if not en_sents or not zh_sents:
        return {"pairs": [], "unpaired_en": sorted(en_ids, key=_sid_num), "unpaired_zh": sorted(zh_ids, key=_sid_num)}
    name_a, name_b = names
    en_list = "\n".join(f"{s['id']}: {s['text']}" for s in en_sents)
    zh_list = "\n".join(f"{s['id']}: {s['text']}" for s in zh_sents)
    out = call_json(
        system=f"You align sentences between the {name_a} and {name_b} versions of the same section of a regulatory "
               "filing. Produce pairs whose two sides express the same content. A pair may be 1-1, 1-many or many-1 "
               f"(one {name_a} sentence rendered as two {name_b} sentences, or vice versa). Sentence order can differ "
               "between the two languages. Every sentence id appears in at most one pair. If a sentence has no "
               "counterpart at all (content omitted on the other side), list it as unpaired rather than forcing a "
               "match. Use the ids exactly as given. Score is your confidence (0-1) that the pair is a translation "
               "correspondence, regardless of whether the details agree.",
        user=f"{name_a.upper()} SENTENCES:\n{en_list}\n\n{name_b.upper()} SENTENCES:\n{zh_list}",
        schema=PAIR_SCHEMA, model=FAST, cache_key=_h("pairs", en_list, zh_list), run_dir=run_dir,
    )
    used_en, used_zh, pairs = set(), set(), []
    for p in out.get("pairs", []):
        e = [x for x in (p.get("en_ids") or []) if isinstance(x, str) and x in en_ids and x not in used_en]
        z = [x for x in (p.get("zh_ids") or []) if isinstance(x, str) and x in zh_ids and x not in used_zh]
        e = list(dict.fromkeys(e)); z = list(dict.fromkeys(z))
        if not e or not z:
            continue
        used_en.update(e); used_zh.update(z)
        pairs.append({"en_ids": sorted(e, key=_sid_num), "zh_ids": sorted(z, key=_sid_num),
                      "score": _clamp(p.get("score"), 0.7)})
    pairs.sort(key=lambda p: _sid_num(p["en_ids"][0]))
    return {"pairs": pairs,
            "unpaired_en": sorted(en_ids - used_en, key=_sid_num),
            "unpaired_zh": sorted(zh_ids - used_zh, key=_sid_num)}


def align(blocks_en: dict, blocks_zh: dict, glossary: list, run_dir: str, on_progress,
          languages: dict | None = None) -> dict:
    names = _names(_languages(blocks_en, blocks_zh, languages))
    h_en = _headings(blocks_en)
    h_zh = _headings(blocks_zh)

    def spans(blocks, hs):
        # (heading_block_or_None, start, end) for preamble + each heading
        out = [(None, 0, hs[0][0] if hs else None)]
        for n, (i, b) in enumerate(hs):
            end = hs[n + 1][0] if n + 1 < len(hs) else None
            out.append((b, i + 1, end))
        return out

    sp_en = spans(blocks_en, h_en)
    sp_zh = spans(blocks_zh, h_zh)
    matches, un_en, un_zh = _align_sections([b for _, b in h_en], [b for _, b in h_zh], run_dir, names)

    # Section list in EN document order; preamble first if both sides have text before the first heading.
    jobs: list[dict] = []
    pre_en = _section_sentences(blocks_en, *sp_en[0][1:])
    pre_zh = _section_sentences(blocks_zh, *sp_zh[0][1:])
    if pre_en and pre_zh:
        pre_label_b = "前言" if languages_is_cjk(blocks_zh, languages) else "PREAMBLE"
        jobs.append({"en_heading": "PREAMBLE", "zh_heading": pre_label_b, "score": 1.0, "en": pre_en, "zh": pre_zh,
                     "page_en": pre_en[0]["page"]})
    for ei, zi, score in matches:
        hb_en, s_en, e_en = sp_en[ei + 1]
        hb_zh, s_zh, e_zh = sp_zh[zi + 1]
        jobs.append({"en_heading": hb_en["text"], "zh_heading": hb_zh["text"], "score": score,
                     "en": _section_sentences(blocks_en, s_en, e_en),
                     "zh": _section_sentences(blocks_zh, s_zh, e_zh),
                     "page_en": hb_en["page"]})
    for n, job in enumerate(jobs, start=1):
        job["id"] = f"sec_{n}"

    unaligned_sections = (
        [{"lang": "en", "heading": h_en[i][1]["text"], "page": h_en[i][1]["page"]} for i in un_en] +
        [{"lang": "zh", "heading": h_zh[i][1]["text"], "page": h_zh[i][1]["page"]} for i in un_zh]
    )
    on_progress(f"Aligned {len(jobs)} sections, {len(unaligned_sections)} unaligned",
                {"unaligned_sections": len(unaligned_sections), "sections": len(jobs)})

    results: dict[str, dict] = {}
    total = len(jobs)
    if total:
        with ThreadPoolExecutor(max_workers=6) as ex:
            futs = {ex.submit(_align_pairs, j["id"], j["en"], j["zh"], run_dir, names): j for j in jobs}
            done = 0
            for fut in as_completed(futs):
                j = futs[fut]
                done += 1
                try:
                    results[j["id"]] = fut.result()
                except Exception as e:
                    print(f"[align] pair alignment failed for {j['id']}: {e}")
                    results[j["id"]] = {"pairs": [], "unpaired_en": [s["id"] for s in j["en"]],
                                        "unpaired_zh": [s["id"] for s in j["zh"]]}
                on_progress(f"Aligning {done}/{total} sections")

    sections, unaligned_sentences = [], []
    pn = 0
    for j in jobs:
        r = results.get(j["id"], {"pairs": [], "unpaired_en": [], "unpaired_zh": []})
        pairs = []
        for p in r["pairs"]:
            pn += 1
            pairs.append({"id": f"p_{pn:03d}", "en_ids": p["en_ids"], "zh_ids": p["zh_ids"], "score": p["score"]})
        sections.append({"id": j["id"], "en_heading": j["en_heading"], "zh_heading": j["zh_heading"],
                         "score": j["score"], "page": j["page_en"], "pairs": pairs})
        unaligned_sentences += [{"lang": "en", "id": s, "section_id": j["id"]} for s in r["unpaired_en"]]
        unaligned_sentences += [{"lang": "zh", "id": s, "section_id": j["id"]} for s in r["unpaired_zh"]]

    return {"sections": sections, "unaligned_sections": unaligned_sections,
            "unaligned_sentences": unaligned_sentences}


if __name__ == "__main__":
    import sys
    import extract
    en = extract.extract_pdf(sys.argv[1], "en")
    zh = extract.extract_pdf(sys.argv[2], "zh")
    rd = sys.argv[3] if len(sys.argv) > 3 else None
    print("meta:", json.dumps(detect_meta(en, zh, rd), ensure_ascii=False))
    g = extract_glossary(en, zh, rd)
    print("glossary:", len(g), json.dumps(g[:5], ensure_ascii=False))
    a = align(en, zh, g, rd, lambda l, d=None: print("  ", l, d or ""))
    print("sections:", len(a["sections"]), "pairs:", sum(len(s["pairs"]) for s in a["sections"]),
          "unaligned_sections:", len(a["unaligned_sections"]), "unaligned_sentences:", len(a["unaligned_sentences"]))
    for s in a["sections"][:12]:
        print(f"  {s['id']} {s['score']:.2f} {s['en_heading'][:40]} <-> {s['zh_heading'][:20]} pairs={len(s['pairs'])}")
