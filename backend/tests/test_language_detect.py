"""extract.detect_language heuristics. Run: python3 -m pytest -q  OR  python3 backend/tests/test_language_detect.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extract import detect_language, joiner, modality_for, short_name, split_sentences  # noqa: E402

EN = ("The Board is pleased to announce that on 23 September 2026 (after trading hours), the Company entered into "
      "the Agreement with the Vendor, pursuant to which the Company has conditionally agreed to acquire, and the "
      "Vendor has conditionally agreed to sell, the Sale Shares for a total consideration of HK$12,400,000.")
ZH_HANT = ("董事會欣然宣佈，於二零二六年九月二十三日（交易時段後），本公司與賣方訂立本協議，據此，本公司有條件同意收購，"
           "而賣方有條件同意出售銷售股份（相當於目標公司已發行股本的60%），總代價為港幣12,400,000元。")
ZH_HANS = ("董事会欣然宣布，于二零二六年九月二十三日（交易时段后），本公司与卖方订立本协议，据此，本公司有条件同意收购，"
           "而卖方有条件同意出售销售股份（相当于目标公司已发行股本的60%），总代价为港币12,400,000元。")
FR = ("Le conseil d'administration a le plaisir d'annoncer que la Société a conclu, le 23 septembre 2026, un accord "
      "avec le vendeur aux termes duquel la Société a accepté d'acquérir les actions pour un montant total de "
      "12,4 millions d'euros. Les résultats du premier semestre sont conformes aux prévisions.")
DE = ("Der Vorstand freut sich bekannt zu geben, dass die Gesellschaft am 23. September 2026 mit dem Verkäufer eine "
      "Vereinbarung geschlossen hat, nach der die Gesellschaft die Aktien für einen Gesamtbetrag von 12,4 Millionen "
      "Euro erwirbt. Die Ergebnisse des ersten Halbjahres entsprechen den Erwartungen.")
IT = ("Il consiglio di amministrazione è lieto di annunciare che la Società ha concluso un accordo con il venditore "
      "per l'acquisto delle azioni per un importo complessivo di 12,4 milioni di euro. I risultati del primo semestre "
      "sono in linea con le previsioni della Società.")
ES = ("El consejo de administración se complace en anunciar que la Sociedad ha celebrado un acuerdo con el vendedor "
      "para la adquisición de las acciones por un importe total de 12,4 millones de euros. Los resultados del primer "
      "semestre están en línea con las previsiones de la Sociedad.")
JA = "当社は、本日、売主との間で株式譲渡契約を締結したことをお知らせいたします。譲渡価額は1,240万香港ドルです。"
KO = "당사는 오늘 매도인과 주식 양도 계약을 체결하였음을 알려드립니다. 양도 대금은 1,240만 홍콩달러입니다."


def test_english():
    assert detect_language(EN) == {"code": "en", "name": "English", "script": "Latn"}


def test_chinese_traditional_and_simplified():
    assert detect_language(ZH_HANT) == {"code": "zh", "name": "Chinese (Traditional)", "script": "Hant"}
    assert detect_language(ZH_HANS) == {"code": "zh", "name": "Chinese (Simplified)", "script": "Hans"}


def test_french_german_italian_spanish():
    assert detect_language(FR) == {"code": "fr", "name": "French", "script": "Latn"}
    assert detect_language(DE) == {"code": "de", "name": "German", "script": "Latn"}
    assert detect_language(IT)["code"] == "it"
    assert detect_language(ES)["code"] == "es"


def test_japanese_korean():
    assert detect_language(JA) == {"code": "ja", "name": "Japanese", "script": "Jpan"}
    assert detect_language(KO) == {"code": "ko", "name": "Korean", "script": "Hang"}


def test_unknown():
    assert detect_language("")["code"] == "und"
    assert detect_language("12345 !!! 67890")["code"] == "und"
    assert detect_language("xyzzy plugh frobnicate")["code"] == "und"     # letters but no function words


def test_mixed_document_is_dominated_by_its_body():
    # an English announcement quoting a Chinese company name stays English
    assert detect_language(EN + " Meridian Pacific (明源太平洋控股有限公司) is the issuer.")["code"] == "en"
    # a Chinese announcement with an English company name stays Chinese
    assert detect_language(ZH_HANT + " Meridian Pacific Holdings Limited")["code"] == "zh"


def test_helpers():
    assert short_name({"name": "Chinese (Traditional)"}) == "Chinese"
    assert short_name({"name": "French"}) == "French"
    assert short_name({}, "English") == "English"
    assert joiner({"script": "Hant"}) == "" and joiner({"script": "Jpan"}) == ""
    assert joiner({"script": "Latn"}) == " " and joiner({"script": "Hang"}) == " "
    assert modality_for({"code": "zh", "script": "Hans"})["firm"] == "将 / 须 / 必须"
    assert modality_for({"code": "fr"})["hedge"] == "peut / pourrait"
    assert modality_for({"code": "und"}) == modality_for({"code": "en"})


def test_split_sentences_follows_script_not_slot():
    fr = "La Société a publié ses résultats. À ce titre, le dividende est maintenu. « Nordlys » désigne la Société."
    # a French document uploaded into the second slot still splits like Latin text
    assert split_sentences(fr, "zh", cjk=False) == [
        "La Société a publié ses résultats.", "À ce titre, le dividende est maintenu.", "« Nordlys » désigne la Société."]
    # defaults are unchanged: slot zh splits on 。 and slot en on ". "
    assert split_sentences("代價為港幣1,210萬元。本公司毋須支付按金。", "zh") == ["代價為港幣1,210萬元。", "本公司毋須支付按金。"]
    assert split_sentences("The Consideration is HK$12.4 million. No deposit is payable.", "en") == [
        "The Consideration is HK$12.4 million.", "No deposit is payable."]


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
