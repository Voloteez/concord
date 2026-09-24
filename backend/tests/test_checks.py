"""Deterministic checks. Run: python3 -m pytest -q  OR  python3 backend/tests/test_checks.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from checks import check_pair, run_checks  # noqa: E402


def _types(found):
    return [f["type"] for f in found]


def _sub(text, span):
    return text[span[0]:span[1]] if span else None


# --- fixture plants --------------------------------------------------------------------------

def test_number_plant_12_4m_vs_1210wan_flagged():
    en = "The Consideration is HK$12.4 million, payable in cash on Completion."
    zh = "代價為港幣1,210萬元，於完成時以現金支付。"
    found = check_pair(en, zh)
    assert _types(found) == ["NUMBER_MISMATCH"], found
    f = found[0]
    assert f["en_span"] == [21, 36] and _sub(en, f["en_span"]) == "HK$12.4 million"
    assert f["zh_span"] == [3, 12] and _sub(zh, f["zh_span"]) == "港幣1,210萬元"
    assert f["explanation"] == "English states HK$12.4 million; Chinese states HK$12.1 million."


def test_48_200_000_vs_4820wan_is_format_not_mismatch():
    en = "For the year ended 31 December 2025, the Target recorded revenue of approximately HK$48,200,000."
    zh = "截至二零二五年十二月三十一日止年度，目標公司錄得收益約港幣4,820萬元。"
    # plain digits vs 萬 notation is the normal HK convention: same value, no finding at all
    assert check_pair(en, zh) == []


def test_date_plant_flagged():
    en = 'If the Conditions are not fulfilled on or before 31 December 2026 (the "Long Stop Date"), the Agreement shall lapse.'
    zh = "倘條件未能於二零二六年十一月三十日（「最後截止日期」）或之前達成，本協議將告失效。"
    found = check_pair(en, zh)
    assert _types(found) == ["DATE_MISMATCH"], found
    f = found[0]
    assert f["en_span"] == [49, 65] and _sub(en, f["en_span"]) == "31 December 2026"
    assert f["zh_span"] == [6, 17] and _sub(zh, f["zh_span"]) == "二零二六年十一月三十日"
    assert f["explanation"] == "English long stop date is 31 December 2026; Chinese is 30 November 2026."


# --- negatives -------------------------------------------------------------------------------

def test_matching_pair_produces_nothing():
    en = "The Consideration is HK$12.4 million, payable in cash on Completion on 31 December 2026."
    zh = "代價為港幣1,240萬元，於二零二六年十二月三十一日完成時以現金支付。"
    assert check_pair(en, zh) == []


def test_60_percent_vs_baifenzhi_liushi_matches():
    en = "The Company will acquire 60% of the issued share capital of the Target."
    assert check_pair(en, "本公司將收購目標公司百分之六十的已發行股本。") == []
    assert check_pair(en, "本公司將收購目標公司60%的已發行股本。") == []


def test_list_letters_and_clause_refs_ignored():
    en = ("(a) the Vendor having obtained all third party consents; (b) no material adverse change; "
          "(1) under Rule 14.07(1) and Rule 14A.76 of the Listing Rules.")
    zh = "(a) 賣方已取得所有第三方同意；(b) 概無重大不利變動；(1) 根據上市規則第14.07(1)條及第14A.76條。"
    assert check_pair(en, zh) == []


def test_stock_code_on_both_sides_not_flagged():
    assert check_pair("Meridian Pacific Holdings Limited (Stock Code: 1877)",
                      "Meridian Pacific Holdings Limited（股份代號：1877）") == []


# --- more forms ------------------------------------------------------------------------------

def test_scaled_forms_and_negatives():
    en = "Revenue was HK$1.5 billion and the loss was HK$(1,200) thousand; 12,400,000 shares were issued."
    zh = "收益為港幣15億元，虧損為港幣(1,200)千元；已發行1,240萬股。"
    found = check_pair(en, zh)
    # 12,400,000 vs 1,240萬 is the same value; everything else matches -> nothing
    assert found == [], found


def test_mdy_and_slash_dates():
    assert check_pair("Dated December 31, 2026.", "日期為2026年12月31日。") == []
    found = check_pair("Dated 31/12/2026.", "日期為二零二六年十二月三十日。")
    assert _types(found) == ["DATE_MISMATCH"]
    assert found[0]["explanation"] == "English date is 31 December 2026; Chinese is 30 December 2026."


def test_currency_mismatch():
    found = check_pair("The Consideration of US$5 million will be settled in cash.",
                       "代價港幣500萬元將以現金支付。")
    assert _types(found) == ["CURRENCY_MISMATCH"], found
    assert found[0]["en_span"] is not None and found[0]["zh_span"] is not None
    # same currency, different word forms -> nothing
    assert check_pair("The Consideration of HK$5 million in Hong Kong dollars.", "代價500萬港元。") == []


def test_one_sided_number():
    found = check_pair("The Vendor holds 3 warehouses and 1,877 staff.", "賣方持有1,877名員工。")
    assert _types(found) == ["NUMBER_MISMATCH"]
    assert found[0]["zh_span"] is None and "3" in found[0]["explanation"]


def test_chinese_common_words_not_numbers():
    assert check_pair("General information and all other matters.", "一般資料及一切其他事項。") == []


# --- run_checks over an alignment ------------------------------------------------------------

def test_run_checks_shape():
    alignment = {"sections": [{"id": "sec_1", "en_heading": "THE ACQUISITION AGREEMENT", "zh_heading": "收購協議",
                               "pairs": [{"id": "p_001", "en_ids": ["en_s1"], "zh_ids": ["zh_s1"]},
                                         {"id": "p_002", "en_ids": ["en_s2", "en_s3"], "zh_ids": ["zh_s2"]}]}],
                 "unaligned_sections": [], "unaligned_sentences": []}
    idx_en = {"en_s1": {"text": "The Consideration is HK$12.4 million, payable in cash on Completion.", "page": 2},
              "en_s2": {"text": "The Target has 12 lorries.", "page": 2},
              "en_s3": {"text": "It also has 3 warehouses.", "page": 2}}
    idx_zh = {"zh_s1": {"text": "代價為港幣1,210萬元，於完成時以現金支付。", "page": 2},
              "zh_s2": {"text": "目標公司有12輛貨車及3個倉庫。", "page": 2}}
    out = run_checks(alignment, idx_en, idx_zh)
    assert len(out) == 1
    f = out[0]
    assert f["type"] == "NUMBER_MISMATCH" and f["source"] == "deterministic" and f["pair_id"] == "p_001"
    assert f["section"] == "THE ACQUISITION AGREEMENT" and f["confidence"] == 1.0
    assert f["en"]["page"] == 2 and f["en"]["span"] == [21, 36] and f["zh"]["span"] == [3, 12]
    assert "severity" not in f and "status" not in f


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


def test_rule_and_chapter_references_ignored():
    en = "subject to the requirements under Chapter 14 and Chapter 14A of the Listing Rules (Rule 14.07)."
    zh = "須遵守上市規則第14章及第14A章項下的規定（第14.07條）。"
    assert check_pair(en, zh) == []
    assert check_pair('"SFO" means the Securities and Futures Ordinance (Chapter 571 of the Laws of Hong Kong)',
                      "「證券及期貨條例」指香港法例第571章證券及期貨條例") == []


def test_currency_code_prefixed_numbers_match():
    en = "a registered capital of RMB5,000,000, and approximately RMB9,300,000 (equivalent to approximately HK$10,100,000)."
    zh = "註冊資本為人民幣5,000,000元，約人民幣930萬元（相當於約港幣1,010萬元）。"
    assert check_pair(en, zh) == []


def test_currency_code_glued_to_digits_is_detected():
    en = "approximately RMB9,300,000 (equivalent to approximately HK$10,100,000) was derived from the PRC subsidiary."
    zh = "約人民幣930萬元（相當於約港幣1,010萬元）來自中國附屬公司。"
    assert check_pair(en, zh) == []
