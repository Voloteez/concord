"""classify.py. Run: python3 -m pytest -q  OR  python3 backend/tests/test_classify.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from classify import classify, recount  # noqa: E402

GLOSSARY = [{"en": "the Company", "zh": "本公司"}, {"en": "the Group", "zh": "本集團"},
            {"en": "Independent Shareholders", "zh": "獨立股東"}, {"en": "EGM", "zh": "股東特別大會"}]
ALIGNMENT = {"sections": [
    {"id": "sec_1", "en_heading": "RISK FACTORS", "zh_heading": "風險因素", "pairs": []},
    {"id": "sec_2", "en_heading": "REASONS FOR AND BENEFITS OF THE ACQUISITION", "zh_heading": "進行收購事項的理由及裨益", "pairs": []},
    {"id": "sec_3", "en_heading": "", "zh_heading": "風險提示", "pairs": []},
], "unaligned_sections": [{"lang": "zh", "heading": "釋義補充", "page": 6}]}


def _f(type_, *, pair_id=None, sentence_id=None, source="llm", section="GENERAL", en_text="x", zh_text="y",
       en_span=None, zh_span=None, page=1, expl="e", conf=0.8):
    d = {"type": type_, "source": source, "section": section,
         "en": {"page": page, "text": en_text, "span": en_span}, "zh": {"page": page, "text": zh_text, "span": zh_span},
         "explanation": expl, "confidence": conf}
    if pair_id:
        d["pair_id"] = pair_id
    if sentence_id:
        d["sentence_id"] = sentence_id
    return d


def test_escalation_omission_minor_with_number():
    s = "The Vendor shall receive 3 further tranches."
    f = _f("OMISSION_MINOR", sentence_id="en_s9", en_text=s, en_span=[0, len(s)], zh_text="賣方。", expl="Absent from Chinese")
    out, _ = classify([], [f], ALIGNMENT, GLOSSARY, "EN")
    assert out[0]["type"] == "OMISSION_MATERIAL" and out[0]["severity"] == "Critical"
    # date, modal and glossary term escalate too
    for txt in ["Completion is expected on 31 December 2026.", "The purchaser may terminate.", "the Independent Shareholders approve"]:
        g = _f("OMISSION_MINOR", sentence_id="en_s9", en_text=txt, en_span=[0, len(txt)])
        assert classify([], [g], ALIGNMENT, GLOSSARY, "EN")[0][0]["type"] == "OMISSION_MATERIAL", txt
    # plain boilerplate stays minor / Cosmetic
    b = "Shareholders and potential investors should exercise caution when dealing in the Shares."
    h = _f("OMISSION_MINOR", sentence_id="en_s10", en_text=b, en_span=[0, len(b)], zh_text="股東務請審慎。")
    r, _ = classify([], [h], ALIGNMENT, GLOSSARY, "EN")
    assert r[0]["type"] == "OMISSION_MINOR" and r[0]["severity"] == "Cosmetic"


def test_hedge_change_in_risk_section_is_critical():
    f = _f("HEDGE_CHANGE", pair_id="p_010", section="RISK FACTORS")
    assert classify([], [f], ALIGNMENT, GLOSSARY, "EN")[0][0]["severity"] == "Critical"
    # ZH-only heading with 風險 (finding.section falls back to the ZH heading)
    g = _f("HEDGE_CHANGE", pair_id="p_011", section="風險提示")
    assert classify([], [g], ALIGNMENT, GLOSSARY, "EN")[0][0]["severity"] == "Critical"
    # ordinary section stays Material
    h = _f("HEDGE_CHANGE", pair_id="p_012", section="REASONS FOR AND BENEFITS OF THE ACQUISITION")
    assert classify([], [h], ALIGNMENT, GLOSSARY, "EN")[0][0]["severity"] == "Material"
    # MEANING_SHIFT in a risk section is not escalated (rule is HEDGE_CHANGE only)
    i = _f("MEANING_SHIFT", pair_id="p_013", section="RISK FACTORS")
    assert classify([], [i], ALIGNMENT, GLOSSARY, "EN")[0][0]["severity"] == "Material"


def test_dedupe_keeps_deterministic():
    det = [_f("NUMBER_MISMATCH", pair_id="p_001", source="deterministic", conf=1.0),
           _f("NUMBER_MISMATCH", pair_id="p_001", source="deterministic", conf=1.0)]   # exact duplicate
    llm = [_f("MEANING_SHIFT", pair_id="p_001"), _f("WORDING", pair_id="p_001"), _f("WORDING", pair_id="p_002"),
           _f("WORDING", pair_id="p_002")]
    out, counts = classify(det, llm, ALIGNMENT, GLOSSARY, "EN")
    assert [(f["type"], f["pair_id"], f["source"]) for f in out] == [
        ("NUMBER_MISMATCH", "p_001", "deterministic"), ("WORDING", "p_002", "llm")]
    assert counts["total"] == 2


def test_ranking_ids_and_fields():
    det = [_f("FORMAT", pair_id="p_030", source="deterministic", page=4, conf=1.0),
           _f("DATE_MISMATCH", pair_id="p_020", source="deterministic", page=3, conf=1.0)]
    llm = [_f("WORDING", pair_id="p_005", page=1),
           _f("HEDGE_CHANGE", pair_id="p_040", page=4, section="REASONS FOR AND BENEFITS OF THE ACQUISITION"),
           _f("NUMBER_MISMATCH", pair_id="p_002", page=2),
           _f("MEANING_SHIFT", pair_id="p_015", page=2)]
    out, counts = classify(det, llm, ALIGNMENT, GLOSSARY, "EN")
    assert [f["severity"] for f in out] == ["Critical", "Critical", "Material", "Material", "Cosmetic", "Cosmetic"]
    assert [f["en"]["page"] for f in out] == [2, 3, 2, 4, 1, 4]
    assert [f["id"] for f in out] == [f"f_{i:03d}" for i in range(1, 7)]
    for f in out:
        assert f["status"] == "unreviewed" and f["dismiss_reason"] is None and f["note"] is None
        assert set(f) >= {"id", "type", "severity", "source", "section", "en", "zh", "explanation", "confidence",
                          "status", "dismiss_reason", "note"}
    assert counts == {"critical": 2, "material": 2, "cosmetic": 2, "unaligned_sections": 1, "reviewed": 0, "total": 6}


def test_omission_wording_and_recount():
    s = "(c) the Independent Shareholders having approved the Acquisition at the EGM."
    f = _f("OMISSION_MATERIAL", sentence_id="en_s7", en_text=s, en_span=[0, len(s)], zh_text="(b) 賣方…",
           expl="Condition (c) is absent from the Chinese version", conf=0.94)
    out, _ = classify([], [f], ALIGNMENT, GLOSSARY, "EN")
    assert out[0]["explanation"].endswith("omitted from Chinese.")
    # already phrased -> untouched
    g = dict(f, explanation="Condition (c) is omitted from Chinese.")
    assert classify([], [g], ALIGNMENT, GLOSSARY, "EN")[0][0]["explanation"] == "Condition (c) is omitted from Chinese."
    # no authoritative version -> explanation left alone
    assert classify([], [f], ALIGNMENT, GLOSSARY, "none")[0][0]["explanation"] == f["explanation"]
    out[0]["status"] = "confirmed"
    c = recount(out + [dict(out[0], id="f_002", status="dismissed"), dict(out[0], id="f_003", status="unreviewed")], [])
    assert c == {"critical": 3, "material": 0, "cosmetic": 0, "unaligned_sections": 0, "reviewed": 2, "total": 3}


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
