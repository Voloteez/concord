"""Locale-aware deterministic checks (fr / de / it / es / pt / nl). Run: python3 backend/tests/test_checks_locales.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from checks import check_pair, extract_dates, extract_numbers, run_checks  # noqa: E402

FR = ("en", "fr", ("English", "French"))
DE = ("en", "de", ("English", "German"))
IT = ("en", "it", ("English", "Italian"))
ES = ("en", "es", ("English", "Spanish"))


def _types(found):
    return [f["type"] for f in found]


def _sub(text, span):
    return text[span[0]:span[1]] if span else None


# --- the cases from the brief ------------------------------------------------------------------

def test_fr_millions_deuros_vs_eur_million_matches():
    assert check_pair("The net result was €12.4 million.", "Le résultat net s'élève à 12,4 millions d'euros.", *FR) == []
    assert check_pair("The net result was EUR 12.4 million.", "Le résultat net s'élève à 12,4 millions d'euros.", *FR) == []


def test_fr_space_grouping_vs_comma_grouping_matches():
    assert check_pair("Revenue of 1,234,567 was recorded.", "Un chiffre d'affaires de 1 234 567 a été enregistré.", *FR) == []
    # narrow no-break space (U+202F) and no-break space (U+00A0) are what French typesetting actually emits
    assert check_pair("Revenue of 1,234,567 was recorded.", "Un chiffre d'affaires de 1 234 567 a été enregistré.", *FR) == []
    assert check_pair("Revenue of 1,234,567.89 was recorded.", "Un chiffre d'affaires de 1 234 567,89 a été enregistré.", *FR) == []


def test_fr_date_matches_and_mismatches():
    assert check_pair("Dated 24 September 2026.", "Fait le 24 septembre 2026.", *FR) == []
    en = "The results were published on 24 October 2026."
    fr = "Les résultats ont été publiés le 24 septembre 2026."
    found = check_pair(en, fr, *FR)
    assert _types(found) == ["DATE_MISMATCH"], found
    assert _sub(en, found[0]["en_span"]) == "24 October 2026"
    assert _sub(fr, found[0]["zh_span"]) == "24 septembre 2026"
    assert found[0]["explanation"] == "English date is 24 October 2026; French is 24 September 2026."


def test_de_period_grouping_comma_decimal_matches():
    assert check_pair("The amount is 1,234,567.89.", "Der Betrag beträgt 1.234.567,89.", *DE) == []
    assert check_pair("A loss of EUR 2.5 billion.", "Ein Verlust von 2,5 Mrd. Euro.", *DE) == []
    assert check_pair("Revenue of EUR 148.6 million.", "Umsatz von 148,6 Millionen Euro.", *DE) == []


def test_es_percent_with_space_matches():
    assert check_pair("A margin of 7.5%.", "Un margen del 7,5 %.", *ES) == []
    assert check_pair("A margin of 7.5 per cent on 24 September 2026.", "Un margen del 7,5 por ciento el 24 de septiembre de 2026.", *ES) == []


# --- more locale forms -------------------------------------------------------------------------

def test_de_ch_apostrophe_grouping_and_chf():
    assert check_pair("The amount is CHF 1,234,567.89.", "Der Betrag beträgt CHF 1'234'567.89.", *DE) == []
    found = check_pair("The amount is CHF 1,234,567.89.", "Der Betrag beträgt CHF 1'244'567.89.", *DE)
    assert _types(found) == ["NUMBER_MISMATCH"], found
    # the English currency table is deliberately untouched (no CHF there), so only the German figure gets a prefix
    assert found[0]["explanation"] == "English states 1234567.89; German states CHF 1244567.89."


def test_de_dotted_date_and_stichtag():
    assert check_pair("On 24 September 2026 and 24/09/2026.", "Am 24. September 2026 und am 24.09.2026.", *DE) == []
    found = check_pair("Dated 31 December 2026.", "Stichtag: 30.11.2026.", *DE)
    assert _types(found) == ["DATE_MISMATCH"]


def test_it_and_es_scale_words():
    assert check_pair("Revenue of EUR 12.4 million and EUR 1.2 billion.", "Ricavi di 12,4 milioni di euro e 1,2 miliardi di euro.", *IT) == []
    assert check_pair("Revenue of EUR 12.4 million.", "Ingresos de 12,4 millones de euros.", *ES) == []
    assert check_pair("Debt of EUR 1.2 billion.", "Deuda de 1,2 miles de millones de euros.", *ES) == []
    assert check_pair("Debt of EUR 1.2 billion.", "Deuda de 1.200 millones de euros.", *ES) == []


def test_fr_number_plant_and_hedge_free_currency():
    en = "The net result for the half-year amounted to EUR 12.4 million."
    fr = "Le résultat net du semestre s'établit à 12,1 millions d'euros."
    found = check_pair(en, fr, *FR)
    assert _types(found) == ["NUMBER_MISMATCH"], found
    assert _sub(en, found[0]["en_span"]) == "EUR 12.4 million"
    assert _sub(fr, found[0]["zh_span"]) == "12,1 millions"
    assert found[0]["explanation"] == "English states €12.4 million; French states €12.1 million."
    # currency words in French
    assert check_pair("C$1.2 million in Canadian dollars.", "1,2 million de dollars canadiens.", *FR) == []
    assert check_pair("CHF 3 million in Swiss francs.", "3 millions de francs suisses.", *FR) == []
    found = check_pair("US$5 million will be settled.", "5 millions d'euros seront réglés.", *FR)
    assert _types(found) == ["CURRENCY_MISMATCH"]
    assert found[0]["explanation"] == "English uses USD; French uses EUR."


def test_fr_ordinals_references_and_list_markers_ignored():
    assert check_pair("Sales of 3,000 units on 1 January 2026 (item 1).",
                      "Ventes de 3 000 unités le 1er janvier 2026 (article 1).", *FR) == []
    assert check_pair("(a) under Rule 14.07(1); (b) see page 3.", "(a) au titre de l'article 14.07(1) ; (b) voir page 3.", *FR) == []
    # a single comma before three digits is grouping without a scale word, a decimal with one
    fr_nums = extract_numbers("1,234 actions et 1,250 milliard", "fr")
    assert [n.value for n in fr_nums] == [1234.0, 1.25e9]


def test_locale_extractors_directly():
    assert [d.iso for d in extract_dates("le 1er janvier 2026, le 24 déc. 2026 et le 05/10/2026", "fr")] == \
        ["2026-01-01", "2026-12-24", "2026-10-05"]
    assert [d.iso for d in extract_dates("am 3. März 2026 und am 24.09.2026", "de")] == ["2026-03-03", "2026-09-24"]
    assert [d.iso for d in extract_dates("il 24 settembre 2026", "it")] == ["2026-09-24"]
    assert [d.iso for d in extract_dates("el 24 de septiembre de 2026", "es")] == ["2026-09-24"]
    assert [n.value for n in extract_numbers("12,4 millions d'euros, soit 7,5 % et 84 000 000 actions", "fr")] == \
        [12.4e6, 7.5, 84_000_000.0]
    # English and Chinese dispatch to the untouched extractors
    assert [n.value for n in extract_numbers("HK$12.4 million and 60%", "en")] == [12.4e6, 60.0]
    assert [n.value for n in extract_numbers("港幣1,210萬元及百分之六十", "zh")] == [12.1e6, 60.0]


def test_run_checks_with_languages_and_default():
    alignment = {"sections": [{"id": "sec_1", "en_heading": "RESULTS", "zh_heading": "RÉSULTATS",
                               "pairs": [{"id": "p_001", "en_ids": ["en_s1"], "zh_ids": ["zh_s1"]},
                                         {"id": "p_002", "en_ids": ["en_s2", "en_s3"], "zh_ids": ["zh_s2"]}]}],
                 "unaligned_sections": [], "unaligned_sentences": []}
    idx_en = {"en_s1": {"text": "The net result amounted to EUR 12.4 million.", "page": 1},
              "en_s2": {"text": "Revenue reached EUR 148.6 million.", "page": 1},
              "en_s3": {"text": "Installed capacity is 1,250 MW.", "page": 1}}
    idx_fr = {"zh_s1": {"text": "Le résultat net s'établit à 12,1 millions d'euros.", "page": 1},
              "zh_s2": {"text": "Le chiffre d'affaires atteint 148,6 millions d'euros et la capacité installée 1 250 MW.", "page": 1}}
    languages = {"en": {"code": "en", "name": "English", "script": "Latn"},
                 "zh": {"code": "fr", "name": "French", "script": "Latn"}}
    out = run_checks(alignment, idx_en, idx_fr, languages=languages)
    assert [(f["type"], f["pair_id"]) for f in out] == [("NUMBER_MISMATCH", "p_001")]
    assert out[0]["explanation"] == "English states €12.4 million; French states €12.1 million."
    # without languages the old English/Chinese behaviour is used verbatim
    idx_zh = {"zh_s1": {"text": "代價為港幣1,210萬元，於完成時以現金支付。", "page": 2}}
    idx_en2 = {"en_s1": {"text": "The Consideration is HK$12.4 million, payable in cash on Completion.", "page": 2}}
    al = {"sections": [{"id": "sec_1", "en_heading": "X", "zh_heading": "Y",
                        "pairs": [{"id": "p_001", "en_ids": ["en_s1"], "zh_ids": ["zh_s1"]}]}]}
    f = run_checks(al, idx_en2, idx_zh)[0]
    assert f["explanation"] == "English states HK$12.4 million; Chinese states HK$12.1 million."
    assert f["en"]["span"] == [21, 36] and f["zh"]["span"] == [3, 12]


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
