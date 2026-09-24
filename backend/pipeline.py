"""run_pipeline(run_id, on_progress) — orchestrates extract -> detect -> glossary -> align -> checks+semantic
-> classify and writes every stage file under data/runs/{id}/. See CONTRACT.md."""
from __future__ import annotations

import datetime as _dt
import json
import os
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

import align
import extract

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS_DIR = os.path.join(BASE_DIR, "data", "runs")

SEVERITY = {
    "NUMBER_MISMATCH": "Critical", "DATE_MISMATCH": "Critical", "CURRENCY_MISMATCH": "Critical",
    "OMISSION_MATERIAL": "Critical",
    "HEDGE_CHANGE": "Material", "MEANING_SHIFT": "Material", "SCOPE_CHANGE": "Material",
    "OMISSION_MINOR": "Cosmetic", "WORDING": "Cosmetic", "FORMAT": "Cosmetic",
}
_SEV_RANK = {"Critical": 0, "Material": 1, "Cosmetic": 2}


def run_dir(run_id: str) -> str:
    return os.path.join(RUNS_DIR, run_id)


def _write(path: str, obj) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _read(path: str, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_recount(findings: list[dict], unaligned_sections: list) -> dict:
    """Fallback for classify.recount."""
    c = {"critical": 0, "material": 0, "cosmetic": 0, "unaligned_sections": len(unaligned_sections or []),
         "reviewed": 0, "total": len(findings)}
    for f in findings:
        key = (f.get("severity") or "Cosmetic").lower()
        if key in c:
            c[key] += 1
        if f.get("status") in ("confirmed", "dismissed", "unresolved"):
            c["reviewed"] += 1
    return c


def recount(findings: list[dict], unaligned_sections: list) -> dict:
    try:
        import classify  # noqa
        return classify.recount(findings, unaligned_sections)
    except Exception:
        return local_recount(findings, unaligned_sections)


def _local_classify(det: list[dict], llm: list[dict], alignment: dict) -> tuple[list[dict], dict]:
    """Minimal fallback if classify.py is missing/broken: severity map, dedupe on pair_id, rank, ids."""
    seen = set()
    out = []
    for src in (det, llm):
        for f in src:
            key = f.get("pair_id") or f.get("sentence_id")
            if key and (key, f.get("type")) in seen:
                continue
            if key:
                seen.add((key, f.get("type")))
            g = dict(f)
            g["severity"] = SEVERITY.get(g.get("type"), "Cosmetic")
            g.setdefault("status", "unreviewed")
            g.setdefault("dismiss_reason", None)
            g.setdefault("note", None)
            out.append(g)
    out.sort(key=lambda f: (_SEV_RANK.get(f["severity"], 3), (f.get("en") or {}).get("page") or 0))
    for n, f in enumerate(out, start=1):
        f["id"] = f"f_{n:03d}"
    return out, local_recount(out, alignment.get("unaligned_sections", []))


def run_pipeline(run_id: str, on_progress) -> None:
    """on_progress(stage, label, done=False, detail=None)."""
    rd = run_dir(run_id)
    t0 = time.time()
    meta_in = _read(os.path.join(rd, "meta.json"), {}) or {}
    created_at = meta_in.get("created_at") or _now()
    override = meta_in.get("authoritative")
    if override not in ("EN", "ZH", "none"):
        override = None

    # cached replays finish in well under a second; hold each stage on screen briefly so the
    # progress list stays readable (CONCORD_MIN_STAGE_S=0 to disable)
    min_stage = float(os.environ.get("CONCORD_MIN_STAGE_S", "0.9"))
    stage_started: dict[str, float] = {}

    def progress(stage, label, done=False, detail=None):
        stage_started.setdefault(stage, time.time())
        if done and stage != "done":
            wait = min_stage - (time.time() - stage_started[stage])
            if wait > 0:
                time.sleep(wait)
        try:
            on_progress(stage, label, done, detail)
        except Exception:
            pass

    def fail(msg: str):
        _write(os.path.join(rd, "findings.json"), {
            "run_id": run_id, "status": "error", "error": msg, "created_at": created_at,
            "meta": {"elapsed_s": round(time.time() - t0, 1)},
            "counts": {"critical": 0, "material": 0, "cosmetic": 0, "unaligned_sections": 0, "reviewed": 0, "total": 0},
            "findings": [], "unaligned_sections": [], "glossary": [],
        })
        progress("done", f"Error: {msg}", True, {"error": msg})

    try:
        # ---- extract
        progress("extract", "Extracting text from both PDFs")
        en_pdf, zh_pdf = os.path.join(rd, "en.pdf"), os.path.join(rd, "zh.pdf")
        for p in (en_pdf, zh_pdf):
            if not os.path.exists(p):
                raise FileNotFoundError(f"missing {os.path.basename(p)}")
        with ThreadPoolExecutor(max_workers=2) as ex:
            f_en = ex.submit(extract.extract_pdf, en_pdf, "en")
            f_zh = ex.submit(extract.extract_pdf, zh_pdf, "zh")
            blocks_en, blocks_zh = f_en.result(), f_zh.result()
        _write(os.path.join(rd, "blocks_en.json"), blocks_en)
        _write(os.path.join(rd, "blocks_zh.json"), blocks_zh)
        idx_en, idx_zh = extract.sentence_index(blocks_en), extract.sentence_index(blocks_zh)
        unreadable = {"en": blocks_en["unreadable_pages"], "zh": blocks_zh["unreadable_pages"]}
        n_sent = len(idx_en) + len(idx_zh)
        progress("extract", f"Extracted {blocks_en['pages']}+{blocks_zh['pages']} pages, {n_sent} sentences", True,
                 {"unreadable_pages": unreadable, "en_pages": blocks_en["pages"], "zh_pages": blocks_zh["pages"],
                  "sentences": n_sent})
        if not idx_en or not idx_zh:
            raise RuntimeError("no extractable text on one side (scanned PDF?)")

        # ---- detect
        progress("detect", "Detecting titles and prevailing language")
        try:
            meta = align.detect_meta(blocks_en, blocks_zh, rd)
        except Exception as e:
            print(f"[pipeline] detect_meta failed: {e}")
            meta = {"en_title": "", "zh_title": "", "company": "", "stock_code": "",
                    "authoritative": "none", "authoritative_detected": False}
        if override is not None:
            meta["authoritative"] = override
        authoritative = meta["authoritative"]
        progress("detect", f"Authoritative: {authoritative}" + (" (detected)" if meta["authoritative_detected"] else ""),
                 True, {"authoritative": authoritative, "authoritative_detected": meta["authoritative_detected"]})

        # ---- glossary
        progress("glossary", "Extracting defined terms")
        try:
            glossary = align.extract_glossary(blocks_en, blocks_zh, rd)
        except Exception as e:
            print(f"[pipeline] glossary failed: {e}")
            glossary = []
        meta_out = dict(meta_in)
        meta_out.update(meta)
        meta_out["created_at"] = created_at
        meta_out["glossary"] = glossary
        _write(os.path.join(rd, "meta.json"), meta_out)
        progress("glossary", f"{len(glossary)} defined terms", True, {"glossary_terms": len(glossary)})

        # ---- align
        progress("align", "Aligning sections")
        alignment = align.align(blocks_en, blocks_zh, glossary, rd,
                                lambda label, detail=None: progress("align", label, False, detail))
        _write(os.path.join(rd, "alignment.json"), alignment)
        n_pairs = sum(len(s["pairs"]) for s in alignment["sections"])
        progress("align", f"{len(alignment['sections'])} sections, {n_pairs} sentence pairs, "
                          f"{len(alignment['unaligned_sections'])} unaligned sections", True,
                 {"unaligned_sections": len(alignment["unaligned_sections"]), "pairs": n_pairs,
                  "sections": len(alignment["sections"])})

        # ---- checks + semantic (concurrent)
        progress("checks", "Running deterministic checks")
        progress("semantic", "Judging sentence pairs")

        def do_checks():
            try:
                import checks
                return checks.run_checks(alignment, idx_en, idx_zh) or []
            except Exception as e:
                print(f"[pipeline] checks failed: {e}\n{traceback.format_exc()}")
                progress("checks", f"Warning: checks unavailable ({type(e).__name__})", False, {"warning": str(e)})
                return []

        def do_semantic():
            try:
                import semantic
                return semantic.run_semantic(
                    alignment, idx_en, idx_zh, glossary, authoritative, rd,
                    lambda label, detail=None, *a, **k: progress("semantic", str(label), False, detail),
                ) or []
            except Exception as e:
                print(f"[pipeline] semantic failed: {e}\n{traceback.format_exc()}")
                progress("semantic", f"Warning: semantic unavailable ({type(e).__name__})", False, {"warning": str(e)})
                return []

        with ThreadPoolExecutor(max_workers=2) as ex:
            f_c = ex.submit(do_checks)
            f_s = ex.submit(do_semantic)
            det = f_c.result()
            progress("checks", f"{len(det)} deterministic findings", True, {"count": len(det)})
            llm_findings = f_s.result()
            progress("semantic", f"{len(llm_findings)} semantic findings", True, {"count": len(llm_findings)})

        # ---- classify
        progress("classify", "Classifying and ranking")
        try:
            import classify
            findings, counts = classify.classify(det, llm_findings, alignment, glossary, authoritative)
        except Exception as e:
            print(f"[pipeline] classify failed: {e}\n{traceback.format_exc()}")
            progress("classify", f"Warning: classify unavailable ({type(e).__name__}), using fallback", False,
                     {"warning": str(e)})
            findings, counts = _local_classify(det, llm_findings, alignment)
        counts = dict(counts or {})
        counts.setdefault("unaligned_sections", len(alignment["unaligned_sections"]))
        counts.setdefault("reviewed", 0)
        counts.setdefault("total", len(findings))
        for k in ("critical", "material", "cosmetic"):
            counts.setdefault(k, sum(1 for f in findings if (f.get("severity") or "").lower() == k))

        run = {
            "run_id": run_id,
            "status": "done",
            "created_at": created_at,
            "meta": {
                "en_title": meta.get("en_title", ""), "zh_title": meta.get("zh_title", ""),
                "company": meta.get("company", ""), "stock_code": meta.get("stock_code", ""),
                "authoritative": authoritative,
                "authoritative_detected": bool(meta.get("authoritative_detected")),
                "en_pages": blocks_en["pages"], "zh_pages": blocks_zh["pages"],
                "unreadable_pages": unreadable,
                "elapsed_s": round(time.time() - t0, 1),
            },
            "counts": counts,
            "findings": findings,
            "unaligned_sections": [{"lang": u["lang"], "heading": u["heading"], "page": u.get("page")}
                                   for u in alignment["unaligned_sections"]],
            "glossary": glossary,
        }
        _write(os.path.join(rd, "findings.json"), run)
        progress("classify", f"{counts.get('total', len(findings))} findings", True, {"counts": counts})
        progress("done", "Done", True, {"counts": counts, "elapsed_s": run["meta"]["elapsed_s"]})
    except Exception as e:
        print(f"[pipeline] fatal: {e}\n{traceback.format_exc()}")
        fail(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    import sys
    run_pipeline(sys.argv[1], lambda st, lb, d=False, de=None: print(f"[{st}{' ✓' if d else ''}] {lb} {de or ''}"))
