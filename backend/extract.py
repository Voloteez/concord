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
EN_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\"“])")
ZH_SPLIT_RE = re.compile(r"(?<=[。！？；])")
CJK_JOIN_RE = re.compile(r"(?<=[一-鿿，。、；：「」（）])\s+"
                         r"(?=[一-鿿，。、；：「」（）])")


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


def _raw_blocks(doc, lang: str):
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
                sep = " " if lang == "en" else ""
                text = sep.join(l["text"] for l in grp).strip()
                if lang == "zh":
                    text = CJK_JOIN_RE.sub("", text)
                if not text:
                    continue
                raw.append({"page": pno, "lines": grp, "text": text})
    return _merge_adjacent(raw, lang), page_chars


def _merge_adjacent(raw: list[dict], lang: str) -> list[dict]:
    """Some generators emit one block per line: merge vertically adjacent same-size blocks
    (gap < 0.4 x font size) on the same page back into paragraphs."""
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
                sep = " " if lang == "en" else ""
                text = sep.join(l["text"] for l in prev["lines"]).strip()
                prev["text"] = CJK_JOIN_RE.sub("", text) if lang == "zh" else text
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


def split_sentences(text: str, lang: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if lang == "zh":
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


def extract_pdf(path: str, lang: str) -> dict:
    doc = pymupdf.open(path)
    raw, page_chars = _raw_blocks(doc, lang)
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
            for s in split_sentences(text, lang):
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
    return {"lang": lang, "pages": pages, "unreadable_pages": unreadable, "blocks": blocks}


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
        print(f"== {lang} {path}: pages={out['pages']} unreadable={out['unreadable_pages']} "
              f"blocks={len(out['blocks'])} headings={len(heads)} sentences={sents}")
        for h in heads[:14]:
            print(f"   [p{h['page']} {h['font_size']}] {h['text'][:80]}")
        print("   first sentences:", json.dumps(
            [s['text'][:60] for b in out['blocks'] for s in b['sentences']][:5], ensure_ascii=False))
