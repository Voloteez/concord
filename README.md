# Concord

Bilingual filing consistency checker. Upload the English and Chinese versions of a
regulatory filing (HKEX announcement, TSX/Euronext EN-FR, any pair); Concord aligns them
section by section, finds every number, date, omission and meaning shift that differs,
ranks each finding by what can get someone fined, and produces a sign-off report the
company secretary can attach to the board pack.

Not a translation tool. Never produces the other version; audits the pair.

## Run

```
python3 -m pip install -r backend/requirements.txt
export ANTHROPIC_API_KEY=...
cd backend && uvicorn api:app --port 8000
open http://localhost:8000
```

Click **Load sample pair** for the demo (a synthetic HKEX connected-transaction
announcement with five planted discrepancies and one control — see
`data/sample/answer_key.json`). Regenerate the pair with `python3 backend/make_sample.py`.

## How it works

1. **Extract** — PyMuPDF blocks with page, bbox, font size; headings by font-size ratio and
   numbering pattern; per-language sentence splitting.
2. **Detect** — prevail clause sets the authoritative version; titles, company, stock code.
3. **Glossary** — defined terms from the Definitions / 釋義 section, paired EN–ZH.
4. **Align** — sections, then sentences within each section (1-1, 1-many, many-1); unpaired
   sentences become omission candidates.
5. **Deterministic checks** — numbers (incl. 萬/億, percentages, bracket negatives), dates
   (incl. 二零二六年 forms), currency — normalised and compared. No LLM in the loop.
6. **Semantic analysis** — batched LLM judgments on each aligned pair: hedge change, meaning
   shift, scope change, omission. Spans must be exact substrings or the finding is dropped.
7. **Classify** — severity by rule, not by model opinion; escalations; dedupe; rank.
8. **Review** — Critical and Material open, Cosmetic collapsed; confirm / dismiss / unresolved
   with C / D / U; export locked until every Critical is decided.
9. **Report** — standalone HTML sign-off, print to PDF.

See `CONTRACT.md` for schemas and the API.

## Design choices (the ones judges ask about)

- Counts are in the header because the co-sec's first question is "how bad is it".
- Cosmetic is collapsed because only things that can get someone fined are open by default.
- Export is locked until every Critical is decided because sign-off means every Critical was
  looked at; the UI enforces the policy.
- Numbers are checked deterministically because an LLM should never be the thing that decides
  whether HK$12.4 million equals 港幣1,210萬元.
- No charts. A chart does not help anyone sign off.
