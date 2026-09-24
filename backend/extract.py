"""PDF -> blocks (PyMuPDF). Heading detection. Sentence split. See CONTRACT.md."""
from __future__ import annotations

import os
import re
import statistics
from collections import Counter, defaultdict

import pymupdf

HEADING_RE = [
    re.compile(r"^\d+\.\s"),
    re.compile(r"^\([a-z]\)"),
    re.compile(r"^[一二三四五六七八九十]+、"),
]
PAGE_NO_RE = re.compile(
    r"^\s*(?:[-–—]\s*)?(?:page\s*)?\d+(?:\s*(?:of|/)\s*\d+)?(?:\s*[-–—])?\s*$"
    r"|^\s*第\s*\d+\s*頁(?:\s*，?\s*共\s*\d+\s*頁)?\s*$",
    re.I,
)
ABBREVS = ("No.", "Nos.", "Mr.", "Mrs.", "Ms.", "Dr.", "Ltd.", "Co.", "Inc.", "Corp.", "approx.",
           "e.g.", "i.e.", "etc.", "vs.", "St.", "Jr.")
# sentence starts: Latin capitals incl. accented ones (À É Ü …), brackets, English and French opening quotes
EN_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-ÖØ-Þ(\"“«])")
ZH_SPLIT_RE = re.compile(r"(?<=[。！？；])")
CJK_JOIN_RE = re.compile(r"(?<=[一-鿿，。、；：「」（）])\s+"
                         r"(?=[一-鿿，。、；：「」（）])")

# ---------------------------------------------------------------- languages
# The two upload slots keep their internal keys "en" / "zh" everywhere; those are SLOT names.
# detect_language() tells us what is actually inside a slot. Heuristic, no dependencies.

LANGUAGES = {
    "en": {"name": "English", "script": "Latn"},
    "fr": {"name": "French", "script": "Latn"},
    "de": {"name": "German", "script": "Latn"},
    "it": {"name": "Italian", "script": "Latn"},
    "es": {"name": "Spanish", "script": "Latn"},
    "pt": {"name": "Portuguese", "script": "Latn"},
    "nl": {"name": "Dutch", "script": "Latn"},
    "zh": {"name": "Chinese", "script": "Hani"},
    "ja": {"name": "Japanese", "script": "Jpan"},
    "ko": {"name": "Korean", "script": "Hang"},
}
UNKNOWN = {"code": "und", "name": "Unknown", "script": "Zyyy"}
DEFAULT_LANGUAGES = {"en": {"code": "en", "name": "English", "script": "Latn"},
                     "zh": {"code": "zh", "name": "Chinese", "script": "Hant"}}
CJK_SCRIPTS = ("Hani", "Hant", "Hans", "Jpan", "Hang", "Kore")
# scripts written without spaces between words and with 。 as the full stop
NO_SPACE_SCRIPTS = ("Hani", "Hant", "Hans", "Jpan")

# >= 30 common function words per Latin-script language; apostrophe elisions are separate tokens
_STOPWORDS = {
    "en": "the of and to in a is that for on with as by are be this at from or an it its which will "
          "was were has have been not any all shall may such under other than their there these those into "
          "no more also between about after before over only where who our we you your can could would should",
    "fr": "le la les de des du un une et en est que qui dans pour par sur au aux ce cette ces se sa son ses "
          "ne pas plus ou avec sont a été être ont dont il elle ils nous vous leur leurs notre nos comme mais "
          "aussi entre sous après avant contre chez lors ainsi selon tout tous toute toutes cet l d qu n s c j",
    "de": "der die das und in den von zu mit ist des dem nicht ein eine im für auf sich als auch es an werden "
          "aus er hat dass sie nach wird bei einer um am sind noch wie einem über einen so zum war haben nur oder "
          "aber vor zur bis mehr durch man sein wurde sei diese dieser dieses unter kann können muss soll",
    "it": "il la di che e è un una per in non con sono del della dei delle al alla ai alle nel nella nei lo gli "
          "le da dal dalla si ha hanno come anche ma più o su questo questa questi queste tra fra sul sulla "
          "essere stato stata stati state sarà dovrà può ogni tutti tutte tutto quale quali cui loro",
    "es": "el la los las de del y en un una que es por para con no se al lo su sus como más pero sí o son "
          "ha han fue ser este esta estos estas ese esa entre sobre también hasta desde cuando donde sin ya "
          "cual cuales cada todo todos toda todas puede podrá será deberá otro otra otros otras muy",
    "pt": "o a os as de do da dos das e em um uma que é por para com não se ao à lo seu sua seus suas como "
          "mais mas ou são foi ser este esta estes estas esse essa entre sobre também até desde quando onde sem "
          "já qual quais cada todo todos toda todas pode poderá será deverá outro outra outros outras muito nos",
    "nl": "de het een en van in is dat op te voor met zijn niet aan er ook als bij uit om door maar dan nog "
          "worden wordt heeft hebben werd werden deze dit die zal zullen kan kunnen moet moeten naar over "
          "onder tussen tegen zonder hun onze ons uw geen alle elke ieder meer meest wel waar wie",
}
_STOPSETS = {code: set(words.split()) for code, words in _STOPWORDS.items()}
_HANT_CHARS = set("於這個為說體與國會後來時間經對開關發電機東車馬鳥魚龍點們產業務際實據處讓辦聯華灣顯應總議"
                  "資訊網頁計劃學術權變達選舉億萬約紀錄設備關係")
_HANS_CHARS = set("于这个为说体与国会后来时间经对开关发电机东车马鸟鱼龙点们产业务际实据处让办联华湾显应总议"
                  "资讯网页计划学术权变达选举亿万约纪录设备关系")
_WORD_RE = re.compile(r"[a-zà-öø-ÿœ]+")


# Modality / quantifier vocabulary per language: the semantic prompt lists the two detected languages'
# words side by side, and classify escalates omissions that contain a "modal" word. zh has a Simplified
# variant keyed "zh-Hans"; modality_for() picks it from the script.
MODALITY = {
    "en": {"hedge": "may / could", "firm": "will / shall / must", "expect": "expects / intends",
           "confirm": "confirms / guarantees", "some": "some / certain", "all": "all",
           "modal": ["may", "will", "shall", "must"]},
    "fr": {"hedge": "peut / pourrait", "firm": "va / devra / doit", "expect": "prévoit / a l'intention",
           "confirm": "confirme / garantit", "some": "certains / quelques", "all": "tous / l'ensemble",
           "modal": ["peut", "pourrait", "pourraient", "va", "vont", "devra", "devront", "doit", "doivent"]},
    "de": {"hedge": "kann / könnte", "firm": "wird / muss", "expect": "erwartet / beabsichtigt",
           "confirm": "bestätigt / garantiert", "some": "einige / bestimmte", "all": "alle / sämtliche",
           "modal": ["kann", "können", "könnte", "könnten", "wird", "werden", "muss", "müssen", "soll", "sollen"]},
    "it": {"hedge": "può / potrebbe", "firm": "sarà / dovrà", "expect": "prevede / intende",
           "confirm": "conferma / garantisce", "some": "alcuni / certi", "all": "tutti",
           "modal": ["può", "possono", "potrebbe", "potrebbero", "sarà", "saranno", "dovrà", "dovranno", "deve", "devono"]},
    "es": {"hedge": "puede / podría", "firm": "será / deberá", "expect": "prevé / tiene la intención",
           "confirm": "confirma / garantiza", "some": "algunos / ciertos", "all": "todos",
           "modal": ["puede", "pueden", "podría", "podrían", "será", "serán", "deberá", "deberán", "debe", "deben"]},
    "pt": {"hedge": "pode / poderia", "firm": "será / deverá", "expect": "prevê / pretende",
           "confirm": "confirma / garante", "some": "alguns / certos", "all": "todos",
           "modal": ["pode", "podem", "poderia", "poderiam", "será", "serão", "deverá", "deverão", "deve", "devem"]},
    "nl": {"hedge": "kan / zou kunnen", "firm": "zal / moet", "expect": "verwacht / is voornemens",
           "confirm": "bevestigt / garandeert", "some": "sommige / bepaalde", "all": "alle",
           "modal": ["kan", "kunnen", "zou", "zouden", "zal", "zullen", "moet", "moeten"]},
    "zh": {"hedge": "可能 / 或", "firm": "將 / 須 / 必須", "expect": "預期 / 擬", "confirm": "確認 / 保證",
           "some": "若干", "all": "所有", "modal": ["可能", "將", "須", "應"]},
    "zh-Hans": {"hedge": "可能 / 或", "firm": "将 / 须 / 必须", "expect": "预期 / 拟", "confirm": "确认 / 保证",
                "some": "若干", "all": "所有", "modal": ["可能", "将", "须", "应"]},
    "ja": {"hedge": "かもしれない / 可能性がある", "firm": "する / しなければならない", "expect": "見込む / 予定",
           "confirm": "確認する / 保証する", "some": "一部", "all": "すべて",
           "modal": ["かもしれない", "なければならない", "予定"]},
    "ko": {"hedge": "수 있다", "firm": "할 것이다 / 해야 한다", "expect": "예상 / 계획", "confirm": "확인 / 보장",
           "some": "일부", "all": "모든", "modal": ["수 있", "해야", "것이다"]},
}


def modality_for(language: dict | None) -> dict:
    """MODALITY entry for a detected language; unknown languages fall back to the English vocabulary."""
    code = (language or {}).get("code") or "en"
    if code == "zh" and (language or {}).get("script") == "Hans":
        return MODALITY["zh-Hans"]
    return MODALITY.get(code) or MODALITY["en"]


def detect_language(text: str) -> dict:
    """Heuristic language detection -> {"code", "name", "script"}. Unknown -> code "und"."""
    text = text or ""
    han = kana = hangul = latin = 0
    for ch in text:
        o = ord(ch)
        if 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or 0xF900 <= o <= 0xFAFF:
            han += 1
        elif 0x3040 <= o <= 0x30FF:
            kana += 1
        elif 0xAC00 <= o <= 0xD7AF or 0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F:
            hangul += 1
        elif ch.isalpha() and o < 0x2000:
            latin += 1
    cjk = han + kana + hangul
    if cjk and (cjk >= 20 or cjk >= 0.2 * (cjk + latin)):
        if hangul and hangul >= 0.3 * cjk:
            return {"code": "ko", "name": "Korean", "script": "Hang"}
        if kana and kana >= 0.05 * cjk:
            return {"code": "ja", "name": "Japanese", "script": "Jpan"}
        hant = sum(1 for ch in text if ch in _HANT_CHARS)
        hans = sum(1 for ch in text if ch in _HANS_CHARS)
        if hans > hant:
            return {"code": "zh", "name": "Chinese (Simplified)", "script": "Hans"}
        return {"code": "zh", "name": "Chinese (Traditional)", "script": "Hant"}
    if not latin:
        return dict(UNKNOWN)
    words = _WORD_RE.findall(text.lower())
    if not words:
        return dict(UNKNOWN)
    scores = {code: sum(1 for w in words if w in stops) for code, stops in _STOPSETS.items()}
    best = max(scores, key=lambda c: scores[c])
    ranked = sorted(scores.values(), reverse=True)
    # need a few hits, and a clear lead over the runner-up
    if ranked[0] < 3 or ranked[0] < 0.05 * len(words) or (len(ranked) > 1 and ranked[0] < 1.2 * ranked[1]):
        return dict(UNKNOWN)
    return {"code": best, "name": LANGUAGES[best]["name"], "script": "Latn"}


def is_cjk(language: dict | None) -> bool:
    return bool(language) and (language.get("script") in CJK_SCRIPTS)


def joiner(language: dict | None) -> str:
    """Separator between lines / sentences: none for Chinese and Japanese, a space otherwise."""
    return "" if language and language.get("script") in NO_SPACE_SCRIPTS else " "


def short_name(language: dict | None, fallback: str = "") -> str:
    """'Chinese (Traditional)' -> 'Chinese' for prose; full names are for headers and prompts."""
    name = (language or {}).get("name") or fallback
    return name.split(" (")[0] if name else fallback



def _is_bold(span: dict) -> bool:
    return bool(span.get("flags", 0) & 16) or "bold" in (span.get("font") or "").lower()


def _line_info(line: dict) -> dict | None:
    spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
    if not spans:
        return None
    text = "".join(s["text"] for s in line["spans"])
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    sizes: Counter = Counter()
    for s in spans:
        sizes[round(float(s.get("size", 0)), 1)] += len(s["text"].strip())
    size = sizes.most_common(1)[0][0]
    bold = all(_is_bold(s) for s in spans)
    return {"text": text, "size": size, "bold": bold, "bbox": list(line["bbox"])}


def _merge_bbox(bboxes: list[list[float]]) -> list[float]:
    return [round(min(b[0] for b in bboxes), 1), round(min(b[1] for b in bboxes), 1),
            round(max(b[2] for b in bboxes), 1), round(max(b[3] for b in bboxes), 1)]


def _split_block_lines(lines: list[dict]) -> list[list[dict]]:
    """Split a PyMuPDF block into runs where the font size (or a leading bold run) changes,
    so a heading glued to its paragraph becomes its own block."""
    groups: list[list[dict]] = []
    for ln in lines:
        if groups and abs(groups[-1][-1]["size"] - ln["size"]) <= 0.6:
            groups[-1].append(ln)
        else:
            groups.append([ln])
    out: list[list[dict]] = []
    for g in groups:
        i = 0
        while i < len(g) and i < 2 and g[i]["bold"]:
            i += 1
        if 0 < i < len(g) and not g[i]["bold"]:
            out.append(g[:i])
            out.append(g[i:])
        else:
            out.append(g)
    return out


def _raw_blocks(doc, lang: str, cjk: bool | None = None):
    """lang is the slot ("en"/"zh"); cjk says whether the text is written without word spaces."""
    if cjk is None:
        cjk = lang == "zh"
    raw = []
    page_chars: dict[int, int] = {}
    for pno, page in enumerate(doc, start=1):
        d = page.get_text("dict")
        page_chars[pno] = len(page.get_text().strip())
        for b in d.get("blocks", []):
            if b.get("type", 0) != 0:
                continue
            lines = [li for li in (_line_info(l) for l in b.get("lines", [])) if li]
            if not lines:
                continue
            for grp in _split_block_lines(lines):
                sep = "" if cjk else " "
                text = sep.join(l["text"] for l in grp).strip()
                if cjk:
                    text = CJK_JOIN_RE.sub("", text)
                if not text:
                    continue
                raw.append({"page": pno, "lines": grp, "text": text})
    return _merge_adjacent(raw, lang, cjk), page_chars


def _merge_adjacent(raw: list[dict], lang: str, cjk: bool | None = None) -> list[dict]:
    """Some generators emit one block per line: merge vertically adjacent same-size blocks
    (gap < 0.4 x font size) on the same page back into paragraphs."""
    if cjk is None:
        cjk = lang == "zh"
    out: list[dict] = []
    for b in raw:
        size = _dominant(b["lines"], "size")
        if out:
            prev = out[-1]
            psize = _dominant(prev["lines"], "size")
            gap = b["lines"][0]["bbox"][1] - max(l["bbox"][3] for l in prev["lines"])
            if (prev["page"] == b["page"] and abs(psize - size) <= 0.6 and gap < 0.4 * size
                    and not PAGE_NO_RE.match(b["text"]) and not PAGE_NO_RE.match(prev["text"])):
                prev["lines"] = prev["lines"] + b["lines"]
                sep = "" if cjk else " "
                text = sep.join(l["text"] for l in prev["lines"]).strip()
                prev["text"] = CJK_JOIN_RE.sub("", text) if cjk else text
                continue
        out.append(b)
    return out


def _dominant(lines: list[dict], key: str):
    c: Counter = Counter()
    for l in lines:
        c[l[key]] += len(l["text"])
    return c.most_common(1)[0][0]


def _body_median(raw: list[dict]) -> float:
    weighted = []
    for b in raw:
        size = _dominant(b["lines"], "size")
        weighted.extend([size] * max(1, len(b["text"]) // 10))
    return statistics.median(weighted) if weighted else 10.0


def _protect_abbrevs(text: str) -> str:
    for a in ABBREVS:
        text = re.sub(re.escape(a) + r"(?=\s)", a.replace(".", "\x00"), text)
    return text


def split_sentences(text: str, lang: str, cjk: bool | None = None) -> list[str]:
    """lang is the slot; cjk (default: slot == "zh") selects the 。！？； splitter."""
    if cjk is None:
        cjk = lang == "zh"
    text = text.strip()
    if not text:
        return []
    if cjk:
        parts = [p for p in ZH_SPLIT_RE.split(text) if p and p.strip()]
        out: list[str] = []
        for p in parts:
            p = p.strip()
            if out and len(p) < 6:
                out[-1] += p
            else:
                out.append(p)
        return out
    protected = _protect_abbrevs(text)
    parts = EN_SPLIT_RE.split(protected)
    return [p.replace("\x00", ".").strip() for p in parts if p.strip()]


def _is_heading(text: str, size: float, bold: bool, median: float) -> bool:
    if len(text) > 300:
        return False
    if size > 1.15 * median:
        return True
    if len(text) <= 200 and bold:
        return True
    # regex-only headings must look like a label, not a list item / sentence
    if len(text) <= 80 and not re.search(r"[.。；;！？!?]$", text) and any(r.match(text) for r in HEADING_RE):
        return True
    return False


def _sample_text(doc, max_chars: int = 4000) -> str:
    parts: list[str] = []
    n = 0
    for page in doc:
        t = page.get_text()
        parts.append(t)
        n += len(t)
        if n >= max_chars:
            break
    return "".join(parts)[:max_chars]


def extract_pdf(path: str, lang: str) -> dict:
    """lang is the SLOT ("en" or "zh"), used for ids. The language inside is detected."""
    doc = pymupdf.open(path)
    language = detect_language(_sample_text(doc))
    cjk = language["script"] in NO_SPACE_SCRIPTS
    raw, page_chars = _raw_blocks(doc, lang, cjk)
    pages = len(doc)
    unreadable = [p for p in range(1, pages + 1) if page_chars.get(p, 0) < 20]

    seen: dict[tuple, set] = defaultdict(set)
    for b in raw:
        y = round(b["lines"][0]["bbox"][1] / 5)
        seen[(b["text"], y)].add(b["page"])
    repeated = {k for k, v in seen.items() if len(v) >= 3 and len(k[0]) <= 120}

    median = _body_median(raw)
    blocks = []
    s_n = 0
    b_n = 0
    for b in raw:
        text = b["text"]
        y = round(b["lines"][0]["bbox"][1] / 5)
        if PAGE_NO_RE.match(text) or (text, y) in repeated:
            continue
        size = _dominant(b["lines"], "size")
        bold = all(l["bold"] for l in b["lines"])
        heading = _is_heading(text, size, bold, median)
        b_n += 1
        sentences = []
        if not heading:
            for s in split_sentences(text, lang, cjk):
                s_n += 1
                sentences.append({"id": f"{lang}_s{s_n}", "text": s})
        blocks.append({
            "id": f"{lang}_b{b_n}",
            "page": b["page"],
            "bbox": _merge_bbox([l["bbox"] for l in b["lines"]]),
            "font_size": float(size),
            "is_heading": heading,
            "text": text,
            "sentences": sentences,
        })
    doc.close()
    return {"lang": lang, "language": language, "pages": pages, "unreadable_pages": unreadable, "blocks": blocks}


def sentence_index(blocks: dict) -> dict[str, dict]:
    idx: dict[str, dict] = {}
    for b in blocks.get("blocks", []):
        for s in b.get("sentences", []):
            idx[s["id"]] = {"text": s["text"], "page": b["page"], "block_id": b["id"]}
    return idx


def render_page_png(pdf_path: str, page_no: int, out_path: str, zoom: float = 1.5) -> str:
    doc = pymupdf.open(pdf_path)
    try:
        if page_no < 1 or page_no > len(doc):
            raise ValueError(f"page {page_no} out of range 1..{len(doc)}")
        page = doc[page_no - 1]
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        pix.save(out_path)
    finally:
        doc.close()
    return out_path


if __name__ == "__main__":
    import json
    import sys

    for path, lang in zip(sys.argv[1::2], sys.argv[2::2]):
        out = extract_pdf(path, lang)
        heads = [b for b in out["blocks"] if b["is_heading"]]
        sents = sum(len(b["sentences"]) for b in out["blocks"])
        print(f"== {lang} {path}: language={out['language']} pages={out['pages']} unreadable={out['unreadable_pages']} "
              f"blocks={len(out['blocks'])} headings={len(heads)} sentences={sents}")
        for h in heads[:14]:
            print(f"   [p{h['page']} {h['font_size']}] {h['text'][:80]}")
        print("   first sentences:", json.dumps(
            [s['text'][:60] for b in out['blocks'] for s in b['sentences']][:5], ensure_ascii=False))
