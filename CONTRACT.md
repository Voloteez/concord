# Concord — build contract

Bilingual filing consistency checker. One-hour hackathon build. Read the PRD at
`~/Downloads/PRD — Bilingual Filing Consistency Checker.md` for the why; THIS file is
the source of truth for how the pieces fit. Do not deviate from the schemas or paths
below without updating this file.

## Layout

```
concord/
  backend/
    api.py          FastAPI app. Serves frontend/ as static at "/" and the API under /api.
    pipeline.py     run_pipeline(run_id, on_progress) — orchestrates the stages below.
    extract.py      PDF -> blocks (PyMuPDF). Heading detection. Sentence split.
    align.py        LLM alignment: sections, then sentence pairs. Emits unaligned lists.
    checks.py       Deterministic: numbers, dates, currency. Pure Python + cn2an + regex.
    semantic.py     Batched LLM pairwise judgments (Anthropic tool use, structured).
    classify.py     Type -> severity, escalation, dedupe, rank, summary counts.
    report.py       HTML sign-off report from findings + run meta.
    llm.py          One Anthropic client, model constants, JSON-tool helper, disk cache.
  frontend/
    index.html      Single page app (upload / progress / review / report views).
    app.js
    styles.css
  data/
    sample/         en.pdf, zh.pdf, answer_key.json  (demo pair)
    runs/{id}/      en.pdf zh.pdf blocks_en.json blocks_zh.json alignment.json
                    findings.json meta.json llm/ (request/response logs) pages/ (png thumbs)
  fixtures/
    findings.json   Hand-written run object the frontend is built against.
  requirements.txt
  README.md
```

Python 3.14. Installed: fastapi, uvicorn, anthropic, python-multipart, sse-starlette,
pymupdf (import as `pymupdf`, not `fitz`), cn2an. Nothing else without asking.

Run: `cd backend && uvicorn api:app --reload --port 8000` then open http://localhost:8000

## LLM

`ANTHROPIC_API_KEY` is in the environment. `llm.py` exposes:

```python
FAST   = "claude-haiku-4-5-20251001"
STRONG = "claude-sonnet-5"
def call_json(*, system: str, user: str, schema: dict, model: str = FAST,
              cache_key: str | None = None, run_dir: str | None = None) -> dict
```

Uses tool-use with a single tool whose `input_schema` is `schema`, `tool_choice` forced,
temperature 0, max_tokens 8000. Retries once on schema failure. If `cache_key` is given,
the response is cached on disk at `data/cache/{sha256(cache_key)}.json` so the demo run
replays without network. Logs every request/response pair under `{run_dir}/llm/`.

## Stage outputs (all JSON files under data/runs/{id}/)

### blocks_{en|zh}.json

```json
{
  "lang": "en",
  "pages": 6,
  "unreadable_pages": [],
  "blocks": [
    {"id": "en_b12", "page": 3, "bbox": [72, 100, 520, 140], "font_size": 10.5,
     "is_heading": false, "text": "The Consideration of HK$12.4 million ...",
     "sentences": [{"id": "en_s40", "text": "The Consideration of HK$12.4 million ..."}]}
  ]
}
```

Heading rule: font_size > 1.15 × body median, OR matches `^\d+\.\s`, `^\([a-z]\)`,
`^[一二三四五六七八九十]+、`, OR the block is entirely bold. Headings have `sentences: []`.
Sentence ids are globally unique per language (`en_s{n}`, `zh_s{n}`), numbered in
document order. Chinese split on 。！？； then merge fragments under 6 chars into the
previous sentence. English split on `(?<=[.!?])\s+(?=[A-Z("])` with an abbreviation
guard for `No.`, `Mr.`, `Ltd.`, `Co.`, `Inc.`, `approx.`, `e.g.`, `i.e.`.

### alignment.json

```json
{
  "sections": [
    {"id": "sec_1",
     "en_heading": "REASONS FOR AND BENEFITS OF THE ACQUISITION",
     "zh_heading": "進行收購事項的理由及裨益",
     "score": 0.93,
     "pairs": [
       {"id": "p_017", "en_ids": ["en_s40"], "zh_ids": ["zh_s38"], "score": 0.91}
     ]}
  ],
  "unaligned_sections": [{"lang": "zh", "heading": "..."}],
  "unaligned_sentences": [{"lang": "zh", "id": "zh_s77", "section_id": "sec_4"}]
}
```

Pair ids `p_{n:03d}` in document order. A pair may be 1-1, 1-many or many-1.

### findings.json — THE run object the frontend consumes

```json
{
  "run_id": "r_8f3a",
  "status": "done",
  "created_at": "2026-09-24T10:12:00Z",
  "meta": {
    "en_title": "DISCLOSEABLE AND CONNECTED TRANSACTION — ACQUISITION OF 60% OF HARBOUR LOGISTICS",
    "zh_title": "須予披露及關連交易 — 收購海港物流60%股權",
    "company": "Meridian Pacific Holdings Limited",
    "stock_code": "1877",
    "authoritative": "EN",
    "authoritative_detected": true,
    "en_pages": 6, "zh_pages": 6,
    "unreadable_pages": {"en": [], "zh": []},
    "elapsed_s": 41.2
  },
  "counts": {"critical": 3, "material": 2, "cosmetic": 4, "unaligned_sections": 1,
             "reviewed": 0, "total": 9},
  "findings": [
    {
      "id": "f_001",
      "type": "NUMBER_MISMATCH",
      "severity": "Critical",
      "source": "deterministic",
      "section": "THE ACQUISITION AGREEMENT",
      "en": {"page": 2, "text": "The Consideration is HK$12.4 million, payable in cash on Completion.", "span": [21, 36]},
      "zh": {"page": 2, "text": "代價為港幣1,210萬元，於完成時以現金支付。", "span": [3, 12]},
      "explanation": "English states HK$12.4 million; Chinese states HK$12.1 million.",
      "confidence": 1.0,
      "status": "unreviewed",
      "dismiss_reason": null,
      "note": null
    }
  ],
  "unaligned_sections": [{"lang": "zh", "heading": "一般資料", "page": 6}],
  "glossary": [{"en": "the Company", "zh": "本公司"}]
}
```

`span` is `[start, end]` character offsets into `text` (end exclusive). Null span means
highlight nothing on that side. For omissions, the side that lacks the content has
`text` set to the nearest neighbouring sentence and `span: null`.

`type` ∈ NUMBER_MISMATCH · DATE_MISMATCH · CURRENCY_MISMATCH · OMISSION_MATERIAL ·
HEDGE_CHANGE · MEANING_SHIFT · SCOPE_CHANGE · OMISSION_MINOR · WORDING · FORMAT
`severity` ∈ Critical · Material · Cosmetic
`source` ∈ deterministic · llm
`status` ∈ unreviewed · confirmed · dismissed · unresolved
`dismiss_reason` ∈ null · false_positive · acceptable_variation · will_fix_in_source

Severity map (classify.py owns this, LLM never sets severity):
NUMBER/DATE/CURRENCY_MISMATCH, OMISSION_MATERIAL → Critical.
HEDGE_CHANGE, MEANING_SHIFT, SCOPE_CHANGE → Material.
OMISSION_MINOR, WORDING, FORMAT → Cosmetic.
Escalations: OMISSION_MINOR → OMISSION_MATERIAL if the sentence has a number, date,
modal (may/will/shall/must/可能/將/須/應) or glossary term. HEDGE_CHANGE → Critical if
section heading contains Risk/Warning/Condition/風險/警告/條件.
Dedupe: same pair id flagged by both sources → keep deterministic, drop llm.
Rank: severity desc (Critical, Material, Cosmetic), then en.page asc, then id.

## API (FastAPI, prefix /api)

| Method | Path | Body / Returns |
| --- | --- | --- |
| POST | /api/runs | multipart `en` + `zh` PDF files, form `authoritative` (EN/ZH/none, optional). Returns `{"run_id"}` and starts the pipeline in a background thread. |
| POST | /api/runs/sample | No body. Copies data/sample/*.pdf into a new run and starts it. Returns `{"run_id"}`. |
| GET | /api/runs/{id} | The findings.json object. While running, `status` is `running` and `findings` is `[]`. |
| GET | /api/runs/{id}/events | SSE. Each event `data:` is `{"stage": "align", "label": "Aligning 4/9 sections", "done": false, "detail": {...}}`. Final event `{"stage":"done","done":true}`. Stages in order: extract, detect, glossary, align, checks, semantic, classify, done. `detail` may carry `unreadable_pages`, `unaligned_sections`. |
| PATCH | /api/runs/{id}/findings/{fid} | JSON `{status?, dismiss_reason?, note?}`. Returns the updated finding. Persists to findings.json and recomputes `counts.reviewed`. |
| GET | /api/runs/{id}/page/{lang}/{n}.png | PNG thumbnail of page n (1-based), rendered at 1.5x by PyMuPDF, cached under runs/{id}/pages/. |
| GET | /api/runs/{id}/report | HTML sign-off report (standalone, inline CSS, print-ready). |
| GET | /api/runs/{id}/export.json | The full run object as a download. |
| GET | /api/health | `{"ok": true}` |

`GET /` and any non-/api path serve `frontend/index.html` and static files.
CORS open. Errors are `{"error": "message"}` with a 4xx/5xx status.

## Frontend views (one index.html, hash routing: #/ , #/run/{id}, #/run/{id}/report)

Design language: applai / visitors.now. Open Runde from jsDelivr fontsource (400/500/600),
ink `#181925`, body `#3f3f46`, muted `#666`, soft `#737373`, faint `#a3a3a3`, hairline
`#e8e8e8`, surface `#f5f5f5`, accent violet `#9580ff` (hover `#7c5cff`, tint `#f3f1ff`,
soft `#dad9fc`). Cards radius 12px, flat surface or 1px hairline, shadow at most
`0 1px 3px rgba(0,0,0,.08), 0 0 0 1px rgba(0,0,0,.02)`. Every control is a pill.
Headings letter-spacing -0.02em. Severity colours are the ONLY other colours:
Critical `#dc2626`, Material `#f59e0b`, Cosmetic `#94a3b8`, Unaligned amber-300 outline
`#fcd34d`. Chinese passages in `"Noto Sans TC", "PingFang TC", "Open Runde", sans-serif`.
Tabular numbers on counts. Motion: rise 12px + fade, 0.5s cubic-bezier(.16,1,.3,1). No charts.

1. Upload (#/): two drop zones side by side (English / Chinese), detected-language label
   after drop, "Load sample pair" link under them, authoritative radio (EN/ZH/Neither)
   appears once both files are present, Run button disabled until both present.
2. Progress: vertical stage list with ticks driven by SSE; shows unreadable-page and
   unaligned-section counts as they arrive. Auto-advances to review on done.
3. Review (#/run/{id}): header (titles, "EN prevails" chip, Critical/Material/Cosmetic
   counts, "9 of 22 reviewed", Export button locked until every Critical is decided,
   tooltip says why). Left rail 30%: findings grouped Critical (open) / Material (open) /
   Cosmetic (collapsed) / Unaligned sections (amber, bottom). Right pane 70%: EN and ZH
   passages side by side with page chips ("EN p.4", click → page thumbnail modal),
   highlighted spans (violet tint `#f3f1ff` with a violet underline — NOT yellow, brand rule),
   one-sentence explanation, type + confidence + source badge, Confirm / Dismiss /
   Unresolved pills with C / D / U keys, dismiss reason dropdown (required to dismiss),
   note textarea. J/K or arrow keys move between findings. Decisions PATCH optimistically.
4. Report (#/run/{id}/report): iframe of /api/runs/{id}/report with a Download PDF button
   (calls window.print on the iframe) and a JSON export link.

Every layout decision has a one-line rationale in an HTML comment next to it — the
presenter will be asked.

## Python function signatures (module boundaries — both backend agents code to these)

```python
# extract.py
def extract_pdf(path: str, lang: str) -> dict            # blocks_{lang}.json object
def sentence_index(blocks: dict) -> dict[str, dict]      # id -> {"text","page","block_id"}
def render_page_png(pdf_path: str, page_no: int, out_path: str, zoom: float = 1.5) -> str

# align.py  (all LLM calls go through llm.call_json)
def detect_meta(blocks_en: dict, blocks_zh: dict, run_dir: str) -> dict
    # {"en_title","zh_title","company","stock_code","authoritative":"EN"|"ZH"|"none","authoritative_detected":bool}
def extract_glossary(blocks_en: dict, blocks_zh: dict, run_dir: str) -> list[dict]   # [{"en","zh"}]
def align(blocks_en: dict, blocks_zh: dict, glossary: list, run_dir: str, on_progress) -> dict  # alignment.json object
    # on_progress(label: str, detail: dict | None = None)

# checks.py
def run_checks(alignment: dict, idx_en: dict, idx_zh: dict) -> list[dict]
    # returns finding dicts WITHOUT severity/status: {id?, type, source:"deterministic", pair_id,
    #   section, en:{page,text,span}, zh:{page,text,span}, explanation, confidence}

# semantic.py
def run_semantic(alignment: dict, idx_en: dict, idx_zh: dict, glossary: list,
                 authoritative: str, run_dir: str, on_progress) -> list[dict]
    # same finding dict shape, source:"llm", type from the PairJudgment verdicts
    # (PARTIAL_OMISSION -> OMISSION_MINOR; unaligned-sentence omission judged material -> OMISSION_MATERIAL)

# classify.py
def classify(det: list[dict], llm: list[dict], alignment: dict, glossary: list,
             authoritative: str) -> tuple[list[dict], dict]
    # assigns id f_{n:03d}, severity, status="unreviewed", dismiss_reason=None, note=None,
    # applies escalations, dedupes on pair_id, ranks; returns (findings, counts)
def recount(findings: list[dict], unaligned_sections: list) -> dict

# report.py
def render_report(run: dict) -> str     # standalone HTML

# pipeline.py
def run_pipeline(run_id: str, on_progress) -> None
    # reads runs/{id}/en.pdf zh.pdf meta.json(authoritative override), writes every stage file,
    # ends by writing findings.json with status "done" (or "error" + "error" message)
```

A finding's `section` is the EN heading of its section (fall back to ZH heading).
Every finding carries `pair_id` (or `sentence_id` for unaligned omissions) so classify can dedupe.

## Serverless mode (Vercel)

`api/index.py` exposes the same FastAPI app. With `VERCEL` or `CONCORD_SYNC=1` set:
runs live under `/tmp/concord/runs`, `POST /api/runs` and `POST /api/runs/sample` run the
pipeline inside the request and return the FULL run object with `"local": true` (and
`"sample": true` for the demo pair). The frontend then keeps that run client-side
(localStorage), applies decisions locally, renders the report via `POST /api/report`
(body = run object) and loads page thumbnails from `/api/sample/page/{lang}/{n}.png` for the
sample pair. LLM responses for the demo are shipped in `data/cache/` so the hosted demo
replays without network; new uploads call the models live (needs `ANTHROPIC_API_KEY`).

## Languages

Concord compares ANY language pair, not just English/Chinese. Detection is heuristic (no
langdetect / lingua); nothing new is installed.

- **Slots, not languages.** The two upload slots keep their internal keys `en` and `zh`
  everywhere — `blocks_en.json` / `blocks_zh.json`, `finding.en` / `finding.zh`, `idx_en` /
  `idx_zh`, `en_ids` / `zh_ids`, `en_title` / `zh_title`, glossary `{"en","zh"}`, the
  `authoritative` values `"EN"` / `"ZH"` / `"none"` and `unaligned_sections[].lang`. They are
  SLOT names; the frontend maps them to the detected names. Do not rename keys.
- `extract.detect_language(text) -> {"code", "name", "script"}` — e.g. `{"code":"en","name":
  "English","script":"Latn"}`. CJK ideographs → `zh` with script `Hant` ("Chinese (Traditional)")
  or `Hans` ("Chinese (Simplified)"), decided by a small set of characters that differ (於/于 這/这
  個/个 為/为 說/说 體/体 與/与 國/国 …); hiragana/katakana → `ja` "Japanese" (`Jpan`); hangul → `ko`
  "Korean" (`Hang`); otherwise Latin-script stopword scoring over `en fr de it es pt nl` (≥ 30
  function words each, names English / French / German / Italian / Spanish / Portuguese / Dutch);
  fallback `{"code":"und","name":"Unknown","script":"Zyyy"}`. It runs on the first ~4000 chars of
  the PDF text and `extract_pdf` stores the result in the blocks object as `"language"`. Layout
  decisions (joining lines without spaces, splitting on 。！？；) follow the detected script, not the
  slot, so a French PDF in the second slot extracts correctly. `extract.LANGUAGES`, `MODALITY`,
  `modality_for()`, `joiner()`, `short_name()`, `is_cjk()` and `DEFAULT_LANGUAGES` are the shared
  language registry used by the other stages.
- `pipeline.py` writes `meta.languages = {"en": <detect result for slot en>, "zh": <detect result
  for slot zh>}` into `findings.json` (and `meta.json`), emits `detail.languages` on the `detect`
  progress events, warns with a progress label (`detail.warning = "same_language"`) when both
  slots detect the same language, and passes `languages=` to `align.detect_meta`,
  `align.extract_glossary`, `align.align`, `checks.run_checks`, `semantic.run_semantic` and
  `classify.classify`. All of these are keyword arguments with defaults (English / Chinese), so
  old callers and the existing tests are unchanged.
- `align.py`: prompts name the detected languages ("the French and English versions") instead of
  assuming English/Chinese. Prevail-clause detection covers English, Traditional and Simplified
  Chinese (以英文版本為準 / 为准), French (« la version anglaise prévaut », « la version française
  fait foi », « en cas de divergence … version … prévaut »), German (« die englische Fassung ist
  maßgeblich », « im Zweifelsfall gilt die deutsche Fassung »), Italian (« prevale la versione
  inglese/italiana »), Spanish (« prevalecerá la versión inglesa/española »), Portuguese and
  Japanese (英語版が優先). The clause names a LANGUAGE; `detect_meta` maps it to whichever SLOT holds
  that language and returns `"EN"` / `"ZH"` / `"none"` as before (`"none"` also when the named
  language is in neither slot, with `authoritative_detected: true`). Definitions-section headings:
  DEFINITIONS, INTERPRETATION, 釋義, 释义, 定義, 定义, DÉFINITIONS, DEFINITIONEN, DEFINIZIONI,
  DEFINICIONES, DEFINIÇÕES, DEFINITIES, 用語の定義. Term patterns: `"Term" means`,
  `« Terme » désigne`, `„Begriff" bezeichnet`, `"Termine" indica`, `「詞語」指`, `“词语”指`,
  `「用語」とは`; every pattern is tried on both sides.
- `semantic.py`: the PRD system prompt is a template rendered for the two detected languages
  (`build_system_prompt(languages)`): "{name_a} and {name_b} versions", a generic glossary rule
  ("a glossary pair is equivalent; two different defined terms, e.g. the Company and the Group,
  are NOT equivalent") and a per-language modality/quantifier table (`extract.MODALITY`: EN may /
  could vs will / shall / must, expects / intends vs confirms / guarantees; FR peut / pourrait vs
  va / devra / doit, prévoit / a l'intention; DE kann / könnte vs wird / muss, erwartet /
  beabsichtigt; IT può / potrebbe vs sarà / dovrà; ES puede / podría vs será / deberá; PT, NL; ZH
  可能 / 或 vs 將 / 須 / 必須, 預期 / 擬 vs 確認 / 保證 (Simplified variant); JA かもしれない vs する /
  しなければならない; KO). The prompt states that passages labelled EN are the first slot's language
  and ZH the second's; field names `en_span` / `zh_span` stay. `semantic.SYSTEM_PROMPT` is the
  English/Chinese rendering. The omission prompt is templated the same way. Sentences are joined
  with `extract.joiner(language)` (no space for Chinese/Japanese, a space otherwise).
- `checks.py`: numbers, dates and currencies are extracted per detected language code:
  `en` and `zh` use today's code paths unchanged (`ja` shares the Chinese 年月日 / 萬 億 rules);
  `fr de it es pt nl` use locale rules — thousands separators space / U+202F / U+00A0 / `'`
  (de-CH) / `.`, comma decimals ("1 234 567,89", "1.234.567,89", "1'234'567.89"); scale words
  millions / milliards, Mio. / Mrd. / Millionen / Milliarden, milioni / miliardi, millones /
  miles de millones / mil millones, milhões, miljoen / miljard; percentages "7,5 %" / pour cent /
  Prozent / per cento / por ciento; dates "24 septembre 2026", "1er janvier 2026", "24. September
  2026", "24.09.2026", "24 settembre 2026", "24 de septiembre de 2026", "24/09/2026" (day-first
  for all these locales) plus ISO; currencies euros / €, CHF / francs suisses / Franken, dollars
  canadiens, dollars américains, livres sterling and the ISO codes. Unknown Latin languages fall
  back to the English rules. Explanations use the short language names ("English states €12.4
  million; French states €12.1 million.").
- `classify.py`: omission wording is "omitted from {language name}" (short name: "Chinese", not
  "Chinese (Traditional)"); the OMISSION_MINOR → OMISSION_MATERIAL modal test uses each language's
  modal words (`MODALITY[code]["modal"]`); the HEDGE_CHANGE → Critical heading test also matches
  Risque / Avertissement / Condition, Risiko / Warnung / Bedingung, Rischio / Avvertenza /
  Condizione, Riesgo / Advertencia / Condición (plus PT, NL, JA, KO).
- `report.py`: column headers, the glossary table, the "Authoritative version" line ("French
  prevails") and the page counts use `meta.languages[slot]["name"]` (fallback English / Chinese
  for runs recorded before detection); the CJK font stack is applied to a passage only when that
  slot's script is Chinese / Japanese / Korean.
- Second demo pair: `backend/make_sample_fr.py` writes `data/sample_fr/en.pdf` + `fr.pdf`, a
  2-page Euronext/TSX-style half-year results release by "Nordlys Énergie SA" (English / French)
  with three plants — number ("EUR 12.4 million" vs "12,1 millions d'euros"), date (AGM 12 May
  2027 vs 19 mai 2027) and hedge ("may consider" vs "va envisager") — and a French prevail clause
  naming English. Not wired to the API yet.
- Tests: `backend/tests/test_language_detect.py`, `backend/tests/test_checks_locales.py`.
  Every `backend/tests/test_*.py` runs standalone with `python3` (pytest is not installed).
