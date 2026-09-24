"""Generate the second Concord demo pair: data/sample_fr/en.pdf, fr.pdf and answer_key.json.

A fictional Euronext / TSX half-year results press release by Nordlys Énergie SA, in English
and French. The French version deviates from the English in exactly three planted ways:

  1. NUMBER  net result "EUR 12.4 million"            -> "12,1 millions d'euros"
  2. DATE    annual general meeting "12 May 2027"      -> "19 mai 2027"
  3. HEDGE   "the Group may consider ..."              -> "le Groupe va envisager ..."

Every other figure, date and sentence matches (with French typography: "148,6 millions d'euros",
"7,5 %", "1 250 MW", "24 septembre 2026"). Both versions carry a prevail clause naming English.

Run:  python3 backend/make_sample_fr.py          (writes the files, then verifies them)
      python3 backend/make_sample_fr.py --verify (verify only)

Both PDFs use PyMuPDF's built-in Helvetica ("helv" / "hebo") via insert_text, which covers
Latin-1: French accents are fine, but the euro sign, the oe ligature, curly quotes and em dashes
are not — so the text says "EUR", uses straight quotes and plain hyphens. The layout engine is
shared with make_sample.py (its Writer wraps Latin text word by word).
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from make_sample import BODY, HEAD, SMALL, TITLE, Writer  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "data", "sample_fr")

# --------------------------------------------------------------------------
# Content. One list, same order for both languages. Kinds:
#   cname  centred company name    cline  centred cover line    title  centred title
#   h1     heading                 p      paragraph             kf     key-figure line (tight)
#   disc   small print             gap    vertical space
# --------------------------------------------------------------------------

EN_TITLE = "Half-year results 2026: revenue up 7.5%, guidance confirmed"
FR_TITLE = "Résultats semestriels 2026 : chiffre d'affaires en hausse de 7,5 %, objectifs confirmés"

DOC = [
    ("cname", "NORDLYS ÉNERGIE SA", "NORDLYS ÉNERGIE SA"),
    ("cline", "Press release - Regulated information", "Communiqué de presse - Information réglementée"),
    ("cline", "Oslo and Montréal, 24 September 2026", "Oslo et Montréal, le 24 septembre 2026"),
    ("gap", 14),
    ("title", EN_TITLE, FR_TITLE),
    ("gap", 8),

    ("h1", "HIGHLIGHTS OF THE FIRST HALF OF 2026", "FAITS MARQUANTS DU PREMIER SEMESTRE 2026"),
    ("p",
     "Nordlys Énergie SA (Euronext Paris: NRDL; TSX: NRD) (the \"Company\" and, together with its subsidiaries, "
     "the \"Group\") today announces its unaudited consolidated results for the six months ended 30 June 2026.",
     "Nordlys Énergie SA (Euronext Paris : NRDL ; TSX : NRD) (la \"Société\" et, avec ses filiales, le \"Groupe\") "
     "annonce aujourd'hui ses résultats consolidés non audités pour le semestre clos le 30 juin 2026."),
    ("p",
     "Consolidated revenue reached EUR 148.6 million, an increase of 7.5% compared with the first half of 2025, "
     "driven by the full contribution of the Skagen offshore wind farm (1,250 MW) commissioned in November 2025.",
     "Le chiffre d'affaires consolidé atteint 148,6 millions d'euros, en hausse de 7,5 % par rapport au premier "
     "semestre 2025, porté par la contribution en année pleine du parc éolien en mer de Skagen (1 250 MW) mis en "
     "service en novembre 2025."),
    ("p",
     "EBITDA amounted to EUR 41.2 million, representing an EBITDA margin of 27.7%.",
     "L'EBITDA s'élève à 41,2 millions d'euros, soit une marge d'EBITDA de 27,7 %."),
    ("p",
     # PLANT 1: EUR 12.4 million -> 12,1 millions d'euros
     "The net result attributable to shareholders amounted to EUR 12.4 million, compared with EUR 9.8 million "
     "for the first half of 2025.",
     "Le résultat net part du Groupe s'établit à 12,1 millions d'euros, contre 9,8 millions d'euros au premier "
     "semestre 2025."),
    ("p",
     "Electricity production totalled 3,412 GWh over the period and net debt stood at EUR 96.3 million as at "
     "30 June 2026.",
     "La production d'électricité s'est élevée à 3 412 GWh sur la période et la dette nette s'établit à "
     "96,3 millions d'euros au 30 juin 2026."),

    ("h1", "KEY FIGURES", "CHIFFRES CLÉS"),
    ("kf", "Revenue: EUR 148.6 million (EUR 138.2 million in the first half of 2025)",
           "Chiffre d'affaires : 148,6 millions d'euros (138,2 millions d'euros au premier semestre 2025)"),
    ("kf", "EBITDA: EUR 41.2 million (EUR 37.9 million)", "EBITDA : 41,2 millions d'euros (37,9 millions d'euros)"),
    ("kf", "Net result: EUR 12.4 million (EUR 9.8 million)", "Résultat net : 12,4 millions d'euros (9,8 millions d'euros)"),
    ("kf", "Net debt: EUR 96.3 million (EUR 104.1 million as at 31 December 2025)",
           "Dette nette : 96,3 millions d'euros (104,1 millions d'euros au 31 décembre 2025)"),
    ("gap", 6),

    ("h1", "FINANCIAL RESULTS", "RÉSULTATS FINANCIERS"),
    ("p",
     "Revenue from the Nordic segment amounted to EUR 92.1 million and revenue from the Canadian segment to "
     "EUR 56.5 million, of which EUR 18.4 million was generated in Canadian dollars under long-term power "
     "purchase agreements.",
     "Le chiffre d'affaires du segment nordique s'élève à 92,1 millions d'euros et celui du segment canadien à "
     "56,5 millions d'euros, dont 18,4 millions d'euros réalisés en dollars canadiens dans le cadre de contrats "
     "d'achat d'électricité de long terme."),
    ("p",
     "Operating expenses were stable at EUR 107.4 million. Depreciation and amortisation increased to "
     "EUR 22.9 million following the commissioning of Skagen.",
     "Les charges opérationnelles sont stables à 107,4 millions d'euros. Les dotations aux amortissements "
     "augmentent à 22,9 millions d'euros à la suite de la mise en service de Skagen."),
    ("p",
     "The Group had 84,000,000 shares outstanding as at 30 June 2026 and cash and cash equivalents of "
     "EUR 63.0 million.",
     "Le Groupe comptait 84 000 000 actions en circulation au 30 juin 2026 et une trésorerie de "
     "63,0 millions d'euros."),

    ("h1", "OUTLOOK", "PERSPECTIVES"),
    ("p",
     "The Company confirms its full-year 2026 guidance of revenue between EUR 295 million and EUR 305 million "
     "and an EBITDA margin above 26%.",
     "La Société confirme ses objectifs pour l'exercice 2026, soit un chiffre d'affaires compris entre "
     "295 millions et 305 millions d'euros et une marge d'EBITDA supérieure à 26 %."),
    ("p",
     # PLANT 3: may consider -> va envisager
     "Following the commissioning of Skagen, the Group may consider additional investments in offshore storage "
     "capacity in 2027.",
     "À la suite de la mise en service de Skagen, le Groupe va envisager des investissements supplémentaires "
     "dans des capacités de stockage en mer en 2027."),
    ("p",
     "The Board of Directors will propose a dividend of EUR 0.42 per share to the annual general meeting.",
     "Le conseil d'administration proposera un dividende de 0,42 euro par action à l'assemblée générale annuelle."),

    ("h1", "FINANCIAL CALENDAR", "CALENDRIER FINANCIER"),
    ("p",
     "Third-quarter revenue will be published on 12 November 2026.",
     "Le chiffre d'affaires du troisième trimestre sera publié le 12 novembre 2026."),
    ("p",
     # PLANT 2: 12 May 2027 -> 19 mai 2027
     "The annual general meeting will be held in Oslo on 12 May 2027.",
     "L'assemblée générale annuelle se tiendra à Oslo le 19 mai 2027."),
    ("p",
     "The ex-dividend date is expected to be 5 October 2026, with payment on 7 October 2026.",
     "La date de détachement du dividende est prévue le 5 octobre 2026, avec mise en paiement le 7 octobre 2026."),

    ("h1", "ABOUT NORDLYS ÉNERGIE", "À PROPOS DE NORDLYS ÉNERGIE"),
    ("p",
     "Nordlys Énergie SA is an independent producer of renewable electricity with 2,140 MW of installed capacity "
     "in Norway, Denmark and Québec. The Company is listed on Euronext Paris and the Toronto Stock Exchange.",
     "Nordlys Énergie SA est un producteur indépendant d'électricité renouvelable disposant de 2 140 MW de "
     "capacité installée en Norvège, au Danemark et au Québec. La Société est cotée sur Euronext Paris et à la "
     "Bourse de Toronto."),
    ("p",
     "Contact: Investor Relations, investors@nordlys-energie.example",
     "Contact : Relations investisseurs, investors@nordlys-energie.example"),
    ("gap", 10),
    ("disc",
     "This press release is published in English and French. In the event of any discrepancy between the two "
     "versions, the English version shall prevail. This document contains forward-looking statements that "
     "involve risks and uncertainties; actual results may differ materially.",
     "Le présent communiqué est publié en anglais et en français. En cas de divergence entre les deux versions, "
     "la version anglaise prévaut. Ce document contient des déclarations prospectives comportant des risques et "
     "des incertitudes ; les résultats réels peuvent différer sensiblement."),
]

PLANTS = [
    {"plant": 1, "type": "NUMBER_MISMATCH", "expected_severity": "Critical",
     "section": "HIGHLIGHTS OF THE FIRST HALF OF 2026",
     "en_snippet": "The net result attributable to shareholders amounted to EUR 12.4 million, compared with EUR 9.8 million for the first half of 2025.",
     "fr_snippet": "Le résultat net part du Groupe s'établit à 12,1 millions d'euros, contre 9,8 millions d'euros au premier semestre 2025.",
     "note": "EUR 12.4 million in English; 12,1 millions d'euros in French."},
    {"plant": 2, "type": "DATE_MISMATCH", "expected_severity": "Critical",
     "section": "FINANCIAL CALENDAR",
     "en_snippet": "The annual general meeting will be held in Oslo on 12 May 2027.",
     "fr_snippet": "L'assemblée générale annuelle se tiendra à Oslo le 19 mai 2027.",
     "note": "12 May 2027 in English; 19 mai 2027 in French."},
    {"plant": 3, "type": "HEDGE_CHANGE", "expected_severity": "Material",
     "section": "OUTLOOK",
     "en_snippet": "Following the commissioning of Skagen, the Group may consider additional investments in offshore storage capacity in 2027.",
     "fr_snippet": "À la suite de la mise en service de Skagen, le Groupe va envisager des investissements supplémentaires dans des capacités de stockage en mer en 2027.",
     "note": "may consider (conditional) became va envisager (definite)."},
]


def _check_latin1(text, where):
    bad = sorted({c for c in text if ord(c) > 255})
    if bad:
        raise ValueError(f"{where}: characters outside Latin-1 (Helvetica cannot draw them): {bad!r}")


def build(lang, path):
    w = Writer("en")                      # Helvetica + word wrapping suits French as well as English
    idx = 1 if lang == "en" else 2
    for item in DOC:
        kind = item[0]
        if kind == "gap":
            w.y += item[1]
            continue
        text = item[idx]
        _check_latin1(text, f"{lang} {kind}")
        if kind == "disc":
            w.paragraph(text, size=SMALL, lead=SMALL * 1.4, after=4)
        elif kind == "cname":
            w.paragraph(text, size=HEAD, fontname=w.head_font, lead=HEAD * 1.45, center=True, after=2)
        elif kind == "cline":
            w.paragraph(text, center=True, after=1)
        elif kind == "title":
            w.paragraph(text, size=TITLE, fontname=w.head_font, lead=TITLE * 1.4, center=True, after=6)
        elif kind == "h1":
            w.heading(text)
        elif kind == "kf":
            w.paragraph(text, size=BODY, after=1)
        else:
            w.paragraph(text)
    w.save(path)


def write_answer_key(path):
    key = {
        "pair": {"en": "data/sample_fr/en.pdf", "fr": "data/sample_fr/fr.pdf", "authoritative": "EN",
                 "slots": {"en": "English", "zh": "French"}},
        "company": "Nordlys Énergie SA", "stock_code": "",
        "en_title": EN_TITLE, "fr_title": FR_TITLE,
        "expected_findings": PLANTS,
        "notes": [
            "Only the three planted findings above are genuine discrepancies.",
            "The French version uses French typography throughout (12,4 millions d'euros, 7,5 %, 1 250 MW, "
            "24 septembre 2026); none of that must be flagged.",
            "Both versions say the English version prevails: authoritative = EN (slot en), detected.",
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(key, f, ensure_ascii=False, indent=2)


def verify():
    import extract

    ok = True
    en = extract.extract_pdf(os.path.join(OUT_DIR, "en.pdf"), "en")
    fr = extract.extract_pdf(os.path.join(OUT_DIR, "fr.pdf"), "zh")
    print(f"en.pdf: {en['pages']} pages, language {en['language']}, "
          f"{sum(len(b['sentences']) for b in en['blocks'])} sentences, "
          f"{sum(1 for b in en['blocks'] if b['is_heading'])} headings")
    print(f"fr.pdf: {fr['pages']} pages, language {fr['language']}, "
          f"{sum(len(b['sentences']) for b in fr['blocks'])} sentences, "
          f"{sum(1 for b in fr['blocks'] if b['is_heading'])} headings")
    if en["language"]["code"] != "en" or fr["language"]["code"] != "fr":
        print("FAIL: language detection")
        ok = False
    sents_en = {s["text"] for b in en["blocks"] for s in b["sentences"]}
    sents_fr = {s["text"] for b in fr["blocks"] for s in b["sentences"]}
    for p in PLANTS:
        for side, sents, key in (("en", sents_en, "en_snippet"), ("fr", sents_fr, "fr_snippet")):
            if p[key] not in sents:
                print(f"FAIL: plant {p['plant']} {side} sentence not verbatim in the text layer: {p[key][:60]}")
                ok = False
    heads_en = [b["text"] for b in en["blocks"] if b["is_heading"]]
    heads_fr = [b["text"] for b in fr["blocks"] if b["is_heading"]]
    for h_en, h_fr in [(i[1], i[2]) for i in DOC if i[0] == "h1"]:
        if h_en not in heads_en or h_fr not in heads_fr:
            print(f"FAIL: heading not detected: {h_en} / {h_fr}")
            ok = False
    print("verify:", "ok" if ok else "FAILED")
    return ok


def main():
    if "--verify" not in sys.argv:
        os.makedirs(OUT_DIR, exist_ok=True)
        build("en", os.path.join(OUT_DIR, "en.pdf"))
        build("fr", os.path.join(OUT_DIR, "fr.pdf"))
        write_answer_key(os.path.join(OUT_DIR, "answer_key.json"))
        print(f"wrote {OUT_DIR}/en.pdf, fr.pdf, answer_key.json")
    sys.exit(0 if verify() else 1)


if __name__ == "__main__":
    main()
