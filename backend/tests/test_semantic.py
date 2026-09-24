"""semantic.py with a fake llm.call_json. Run: python3 -m pytest -q  OR  python3 backend/tests/test_semantic.py"""
import os
import re
import sys
from contextlib import contextmanager

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import semantic  # noqa: E402
from semantic import find_span, run_semantic  # noqa: E402

EN_HEDGE = "Following Completion, the Group may consider further acquisitions in the logistics sector."
ZH_HEDGE = "完成後，本集團將考慮於物流行業進行進一步收購。"
EN_GROUP = "The Company shall procure the payment of the Consideration from its internal resources."
ZH_GROUP = "本集團須以內部資源促使支付代價。"
EN_SAME = "The Target is principally engaged in the provision of freight forwarding and warehousing services in Hong Kong."
ZH_SAME = "目標公司主要於香港從事貨運代理及倉儲服務。"
EN_PART = "The Vendor shall deliver the share certificates and the board resolutions on Completion."
ZH_PART = "賣方須於完成時交付股票。"
EN_COND = "(c) the Independent Shareholders having approved the Acquisition at the EGM."

ALIGNMENT = {
    "sections": [
        {"id": "sec_1", "en_heading": "REASONS FOR AND BENEFITS OF THE ACQUISITION", "zh_heading": "進行收購事項的理由及裨益",
         "pairs": [{"id": "p_001", "en_ids": ["en_s1"], "zh_ids": ["zh_s1"]},
                   {"id": "p_002", "en_ids": ["en_s2"], "zh_ids": ["zh_s2"]},
                   {"id": "p_003", "en_ids": ["en_s3"], "zh_ids": ["zh_s3"]},
                   {"id": "p_004", "en_ids": ["en_s4"], "zh_ids": ["zh_s4"]}]},
        {"id": "sec_2", "en_heading": "CONDITIONS PRECEDENT", "zh_heading": "先決條件",
         "pairs": [{"id": "p_005", "en_ids": ["en_s5"], "zh_ids": ["zh_s5"]},
                   {"id": "p_006", "en_ids": ["en_s6"], "zh_ids": ["zh_s6"]}]},
    ],
    "unaligned_sections": [],
    "unaligned_sentences": [{"lang": "en", "id": "en_s7", "section_id": "sec_2"},
                            {"lang": "en", "id": "en_s8", "section_id": "sec_2"}],
}
IDX_EN = {"en_s1": {"text": EN_HEDGE, "page": 4}, "en_s2": {"text": EN_GROUP, "page": 4},
          "en_s3": {"text": EN_SAME, "page": 4}, "en_s4": {"text": EN_PART, "page": 4},
          "en_s5": {"text": "(a) the Vendor having obtained all necessary third party consents;", "page": 3},
          "en_s6": {"text": "(b) no material adverse change having occurred.", "page": 3},
          "en_s7": {"text": EN_COND, "page": 3},
          "en_s8": {"text": "Shareholders should refer to the timetable in the circular.", "page": 3}}
IDX_ZH = {"zh_s1": {"text": ZH_HEDGE, "page": 4}, "zh_s2": {"text": ZH_GROUP, "page": 4},
          "zh_s3": {"text": ZH_SAME, "page": 4}, "zh_s4": {"text": ZH_PART, "page": 4},
          "zh_s5": {"text": "(a) 賣方已就收購事項取得所有必要的第三方同意；", "page": 3},
          "zh_s6": {"text": "(b) 並無發生重大不利變動。", "page": 3}}
GLOSSARY = [{"en": "the Company", "zh": "本公司"}, {"en": "the Group", "zh": "本集團"}]

CALLS = []


def _judgment(pid, verdict, en_span=None, zh_span=None, expl="x", conf=0.9):
    return {"pair_id": pid, "verdict": verdict, "en_span": en_span, "zh_span": zh_span,
            "explanation": expl, "confidence": conf}


def fake_call_json(*, system, user, schema, model=None, cache_key=None, run_dir=None):
    CALLS.append({"model": model, "user": user, "cache_key": cache_key, "system": system})
    if "Unpaired sentences to judge" in user:
        return {"results": [
            {"sentence_id": "en_s7", "present_elsewhere": False, "matched_text": None, "material": True,
             "reason": "Condition (c), Independent Shareholders' approval at the EGM, is absent from the Chinese version.",
             "confidence": 0.94},
            {"sentence_id": "en_s8", "present_elsewhere": False, "matched_text": None, "material": False,
             "reason": "Boilerplate cross-reference appears only in English.", "confidence": 0.66},
        ]}
    pids = re.findall(r"^\[(p_\d+)\]", user, re.M)
    js = []
    for pid in pids:
        if pid == "p_001":
            # FAST says MEANING_SHIFT, STRONG says HEDGE_CHANGE -> STRONG must win
            if model == semantic.llm.STRONG:
                js.append(_judgment(pid, "HEDGE_CHANGE", "may consider", "將考慮",
                                    "English is conditional (may consider); Chinese is definite (將考慮).", 0.91))
            else:
                js.append(_judgment(pid, "MEANING_SHIFT", "may consider", "將考慮", "triage", 0.6))
        elif pid == "p_002":
            js.append(_judgment(pid, "MEANING_SHIFT", "The Company", "本集團", "Company vs Group.", 0.88))
        elif pid == "p_003":
            js.append(_judgment(pid, "EQUIVALENT"))
        elif pid == "p_004":
            # whitespace-insensitive span + PARTIAL_OMISSION -> OMISSION_MINOR
            js.append(_judgment(pid, "PARTIAL_OMISSION", "the  board\nresolutions", None,
                                "Board resolutions are not mentioned in Chinese.", 0.8))
        elif pid == "p_005":
            # WORDING with a hallucinated span must be dropped
            js.append(_judgment(pid, "WORDING", "not in the passage at all", None, "wording", 0.5))
        elif pid == "p_006":
            # non-WORDING with a hallucinated span is kept with null span
            js.append(_judgment(pid, "SCOPE_CHANGE", "hallucinated text", "幻覺", "scope", 0.7))
    return {"judgments": js}


@contextmanager
def patched():
    real = semantic.llm.call_json
    semantic.llm.call_json = fake_call_json
    CALLS.clear()
    try:
        yield
    finally:
        semantic.llm.call_json = real


def _run():
    progress = []
    with patched():
        out = run_semantic(ALIGNMENT, IDX_EN, IDX_ZH, GLOSSARY, "EN", None, progress.append)
    return out, progress


def test_find_span():
    assert find_span(EN_HEDGE, "may consider") == [32, 44]
    assert find_span(ZH_HEDGE, "將考慮") == [7, 10]
    assert find_span(EN_PART, "the  board\nresolutions") == [EN_PART.index("the board"), EN_PART.index("resolutions") + len("resolutions")]
    assert find_span(EN_HEDGE, "nope") is None
    assert find_span(EN_HEDGE, None) is None


def test_verdict_mapping_and_strong_wins():
    out, _ = _run()
    by_pair = {f.get("pair_id"): f for f in out if f.get("pair_id")}
    assert by_pair["p_001"]["type"] == "HEDGE_CHANGE"           # STRONG verdict replaced FAST's MEANING_SHIFT
    assert by_pair["p_001"]["confidence"] == 0.91
    assert by_pair["p_002"]["type"] == "MEANING_SHIFT"
    assert "p_003" not in by_pair                                # EQUIVALENT -> nothing
    assert by_pair["p_004"]["type"] == "OMISSION_MINOR"          # PARTIAL_OMISSION -> OMISSION_MINOR
    assert "p_005" not in by_pair                                # WORDING with bad span dropped
    assert by_pair["p_006"]["type"] == "SCOPE_CHANGE"            # kept, spans null
    assert by_pair["p_006"]["en"]["span"] is None and by_pair["p_006"]["zh"]["span"] is None
    for f in out:
        assert f["source"] == "llm" and f["section"] and "severity" not in f


def test_span_conversion():
    out, _ = _run()
    by_pair = {f.get("pair_id"): f for f in out if f.get("pair_id")}
    f = by_pair["p_001"]
    assert f["en"]["span"] == [32, 44] and EN_HEDGE[32:44] == "may consider"
    assert f["zh"]["span"] == [7, 10] and ZH_HEDGE[7:10] == "將考慮"
    assert f["en"]["page"] == 4 and f["zh"]["page"] == 4
    g = by_pair["p_002"]
    assert g["en"]["span"] == [0, 11] and g["zh"]["span"] == [0, 3]
    h = by_pair["p_004"]
    assert EN_PART[h["en"]["span"][0]:h["en"]["span"][1]] == "the board resolutions"
    assert h["zh"]["span"] is None


def test_omission_pass():
    out, _ = _run()
    by_sid = {f.get("sentence_id"): f for f in out if f.get("sentence_id")}
    a = by_sid["en_s7"]
    assert a["type"] == "OMISSION_MATERIAL"
    assert a["en"]["text"] == EN_COND and a["en"]["span"] == [0, len(EN_COND)]
    assert a["zh"]["span"] is None and a["zh"]["text"] == IDX_ZH["zh_s6"]["text"]   # nearest neighbour by order
    assert a["section"] == "CONDITIONS PRECEDENT" and a["en"]["page"] == 3 and a["confidence"] == 0.94
    b = by_sid["en_s8"]
    assert b["type"] == "OMISSION_MINOR" and b["zh"]["span"] is None


def test_passes_models_batches_and_cache_keys():
    _, progress = _run()
    fast = [c for c in CALLS if c["model"] == semantic.llm.FAST]
    strong = [c for c in CALLS if c["model"] == semantic.llm.STRONG]
    assert len(fast) == 2                                      # one FAST batch per section (6 pairs, 2 sections)
    assert all("Pairs to judge:" in c["user"] for c in fast)
    assert any("Unpaired sentences to judge" in c["user"] for c in strong)
    strong_pairs = [c for c in strong if "Pairs to judge:" in c["user"]]
    judged = set()
    for c in strong_pairs:
        judged.update(re.findall(r"^\[(p_\d+)\]", c["user"], re.M))
    assert judged == {"p_001", "p_002", "p_004", "p_005", "p_006"}   # everything not EQUIVALENT
    assert all(re.fullmatch(r"[0-9a-f]{64}", c["cache_key"]) for c in CALLS)
    assert all(c["system"] == semantic.SYSTEM_PROMPT for c in fast)
    assert "Glossary:\nthe Company = 本公司\nthe Group = 本集團" in fast[0]["user"]
    assert "Authoritative version: EN" in fast[0]["user"]
    assert any(p == "Analysing 6/6 pairs" for p in progress), progress


def test_batches_of_ten_within_section():
    recs = [{"pair_id": f"p_{i:03d}", "section_id": "s1" if i < 23 else "s2"} for i in range(30)]
    bs = semantic._batches(recs)
    assert [len(b) for b in bs] == [10, 10, 3, 7]


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok    {name}")
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"FAIL  {name}: {type(e).__name__}: {e}")
    print("all passed" if not failed else f"{failed} failed")
    sys.exit(1 if failed else 0)
