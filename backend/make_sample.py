"""Generate the Concord demo pair: data/sample/en.pdf, zh.pdf and answer_key.json.

A fictional HKEX discloseable and connected transaction announcement by
Meridian Pacific Holdings Limited (stock code 1877). The Chinese version deviates
from the English in exactly six planted ways (see PLANTS below) plus one extra
Chinese-only sub-heading; every other number, date and sentence matches.

Run:  python3 backend/make_sample.py          (writes the files, then verifies them)
      python3 backend/make_sample.py --verify (verify only)

Layout is done by hand (our own line wrapper + insert_text) rather than
insert_textbox so that Chinese lines never break inside a number such as 1,210
and so that CJK punctuation never starts a line. That keeps every planted
sentence verbatim in the text layer.
"""

import json
import os
import re
import sys

import pymupdf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "data", "sample")

PAGE_W, PAGE_H, MARGIN = 595, 842, 60          # A4, 60pt margins
TEXT_W = PAGE_W - 2 * MARGIN
BODY, HEAD, TITLE, SMALL = 10.5, 13.0, 15.0, 9.5   # HEAD > 1.15 x BODY (12.075)

FONTS = {
    "en": {"body": "helv", "head": "hebo", "lead": 14.2},
    "zh": {"body": "china-t", "head": "china-t", "lead": 15.5},
}

# --------------------------------------------------------------------------
# Document content. One list, same order for both languages, so section order
# is guaranteed identical. Kinds:
#   disc   small disclaimer paragraph      cname  centred company name (13pt)
#   cline  centred cover line              title  centred 15pt title
#   h1/h2  headings (13pt)                 p      body paragraph
#   list   (kind, en_lead, zh_lead, en_items, zh_items) tight list block
#   zh_h2 / zh_p   Chinese-only items (en is None)
#   sig_c  centred signature line          gap    vertical space
# --------------------------------------------------------------------------

EN_TITLE = ("DISCLOSEABLE AND CONNECTED TRANSACTION — ACQUISITION OF 60% EQUITY "
            "INTEREST IN HARBOUR LOGISTICS LIMITED")
ZH_TITLE = "須予披露及關連交易 — 收購海港物流有限公司60%股權"

DOC = [
    ("disc",
     "Hong Kong Exchanges and Clearing Limited and The Stock Exchange of Hong Kong Limited "
     "take no responsibility for the contents of this announcement, make no representation "
     "as to its accuracy or completeness and expressly disclaim any liability whatsoever for "
     "any loss howsoever arising from or in reliance upon the whole or any part of the "
     "contents of this announcement.",
     "香港交易及結算所有限公司及香港聯合交易所有限公司對本公告的內容概不負責，對其準確性或完整性亦"
     "不發表任何聲明，並明確表示，概不對因本公告全部或任何部分內容而產生或因倚賴該等內容而引致的任"
     "何損失承擔任何責任。"),
    ("gap", 18),
    ("cname", "MERIDIAN PACIFIC HOLDINGS LIMITED", "明源太平洋控股有限公司"),
    ("cline", "(Incorporated in the Cayman Islands with limited liability)", "（於開曼群島註冊成立的有限公司）"),
    ("cline", "(Stock Code: 1877)", "（股份代號：1877）"),
    ("gap", 18),
    ("title", EN_TITLE, ZH_TITLE),
    ("gap", 10),

    # ---------------------------------------------------------------- INTRODUCTION
    ("h1", "INTRODUCTION", "緒言"),
    ("p",
     "The Board is pleased to announce that on 23 September 2026 (after trading hours), the "
     "Company entered into the Agreement with the Vendor, pursuant to which the Company has "
     "conditionally agreed to acquire, and the Vendor has conditionally agreed to sell, the "
     "Sale Shares, representing 60% of the issued share capital of the Target, for a total "
     "consideration of HK$12,400,000.",
     "董事會欣然宣佈，於二零二六年九月二十三日（交易時段後），本公司與賣方訂立本協議，據此，本公司有"
     "條件同意收購，而賣方有條件同意出售銷售股份（相當於目標公司已發行股本的60%），總代價為港幣"
     "12,400,000元。"),
    ("p",
     "The Acquisition constitutes a discloseable and connected transaction of the Company and "
     "is subject to the reporting, announcement, circular and Independent Shareholders' "
     "approval requirements under Chapter 14 and Chapter 14A of the Listing Rules.",
     "收購事項構成本公司的一項須予披露及關連交易，並須遵守上市規則第14章及第14A章項下的申報、公告、"
     "通函及獨立股東批准規定。"),

    # ---------------------------------------------------------------- AGREEMENT
    ("h1", "THE ACQUISITION AGREEMENT", "收購協議"),
    ("p",
     "The principal terms of the Agreement are summarised below.",
     "本協議的主要條款概述如下。"),
    ("h2", "Date", "日期"),
    ("p", "23 September 2026 (after trading hours)", "二零二六年九月二十三日（交易時段後）"),
    ("h2", "Parties", "訂約方"),
    ("p", "Purchaser: the Company.", "買方：本公司。"),
    ("p",
     "Vendor: Golden Anchor Investments Limited, a company incorporated in the British Virgin "
     "Islands with limited liability, which is wholly owned by Mr. Chan Wai Kwong, a "
     "non-executive Director.",
     "賣方：金錨投資有限公司，一間於英屬處女群島註冊成立的有限公司，由非執行董事陳偉光先生全資擁有。"),
    ("p",
     "The Vendor is a substantial shareholder of the Company holding approximately 18.75% of "
     "the issued Shares and is therefore a connected person of the Company. Further details "
     "are set out in the section headed \"Listing Rules Implications\" below.",
     "賣方為本公司的主要股東，持有約18.75%的已發行股份，因此為本公司的關連人士。進一步詳情載於下文"
     "「上市規則的涵義」一節。"),
    ("h2", "Assets to be acquired", "將予收購的資產"),
    ("p",
     "Pursuant to the Agreement, the Company has conditionally agreed to acquire the Sale "
     "Shares, being 6,000 ordinary shares in the Target, representing 60% of the entire issued "
     "share capital of the Target as at the date of this announcement. The remaining 40% of "
     "the issued share capital of the Target is held by Mr. Lam Tak Shing, an Independent "
     "Third Party, who will continue to hold his interest following Completion.",
     "根據本協議，本公司有條件同意收購銷售股份，即目標公司6,000股普通股，相當於目標公司於本公告日期"
     "全部已發行股本的60%。目標公司餘下40%的已發行股本由獨立第三方林德成先生持有，彼於完成後將繼續持"
     "有其權益。"),
    ("p",
     "The Sale Shares shall be acquired free from all encumbrances and together with all "
     "rights attaching to them as at Completion, including the right to receive all dividends "
     "declared, made or paid on or after the date of Completion.",
     "銷售股份將於完成時在不附帶任何產權負擔的情況下連同所附帶的一切權利予以收購，包括收取於完成日期"
     "或之後宣派、作出或支付的所有股息的權利。"),
    ("h2", "Consideration", "代價"),
    ("p",
     # PLANT 1 (HK$12.4m -> 1,210萬) and PLANT 5 (Company -> 本集團)
     "The Consideration is HK$12.4 million, payable in cash on Completion. The Company shall "
     "procure the payment of the Consideration from its internal resources. No deposit is "
     "payable by the Company prior to Completion.",
     "代價為港幣1,210萬元，於完成時以現金支付。本集團須以內部資源促使支付代價。本公司毋須於完成前支付"
     "任何按金。"),
    ("p",
     "The Consideration was determined after arm's length negotiations between the Company "
     "and the Vendor on normal commercial terms with reference to, among other things, the "
     "unaudited net asset value of the Target of approximately HK$16.8 million as at 30 June "
     "2026, the audited net profit after taxation of the Target of approximately HK$2.52 "
     "million for the year ended 31 December 2025, and the preliminary valuation of the entire "
     "equity interest in the Target of HK$21.0 million as at 30 June 2026 prepared by Ascent "
     "Appraisal Limited, an independent professional valuer, using the market approach.",
     "代價乃由本公司與賣方按一般商業條款經公平磋商後釐定，並經參考（其中包括）目標公司於二零二六年六"
     "月三十日的未經審核資產淨值約港幣1,680萬元、目標公司截至二零二五年十二月三十一日止年度的經審核除"
     "稅後純利約港幣252萬元，以及獨立專業估值師昇華評估有限公司採用市場法編製的目標公司全部股權於二零"
     "二六年六月三十日的初步估值港幣2,100萬元。"),
    ("p",
     "On this basis, the Consideration represents a discount of approximately 1.6% to the "
     "valuation attributable to the Sale Shares of HK$12.6 million and a price-to-earnings "
     "multiple of approximately 8.2 times.",
     "據此，代價較銷售股份應佔估值港幣1,260萬元折讓約1.6%，市盈率約為8.2倍。"),
    ("p",
     "The Directors (other than the independent non-executive Directors, whose views will be "
     "set out in the circular after considering the advice of the Independent Financial "
     "Adviser) consider that the Consideration is fair and reasonable and in the interests of "
     "the Company and the Shareholders as a whole.",
     "董事（獨立非執行董事除外，彼等的意見將於考慮獨立財務顧問的意見後載於通函內）認為，代價屬公平合"
     "理，並符合本公司及股東的整體利益。"),
    ("h2", "Conditions precedent", "先決條件"),
    ("list",
     "Completion is conditional upon the fulfilment of the following Conditions:",
     "完成須待下列條件達成後，方可作實：",
     [
         "(a) the Vendor having delivered to the Company the audited financial statements of "
         "the Target for the year ended 31 December 2025, and there having been no material "
         "adverse change in the business, assets or financial position of the Target since "
         "30 June 2026.",
         "(b) the Vendor having obtained all necessary third-party consents in respect of the "
         "Acquisition.",
         # PLANT 3: this item is deleted from the Chinese list, which is relettered (a)(b)(c)
         "(c) the Independent Shareholders having approved the Acquisition at the EGM.",
         "(d) the warranties given by the Vendor under the Agreement remaining true, accurate "
         "and not misleading in all material respects as at Completion.",
     ],
     [
         "(a) 賣方已向本公司交付目標公司截至二零二五年十二月三十一日止年度的經審核財務報表，且目標公司的"
         "業務、資產或財務狀況自二零二六年六月三十日以來並無重大不利變動；",
         "(b) 賣方已就收購事項取得所有必要的第三方同意；",
         "(c) 賣方根據本協議作出的保證於完成時在所有重大方面仍屬真實、準確且無誤導成分。",
     ]),
    ("p",
     "The Company may waive the Condition relating to the warranties given by the Vendor at "
     "its sole discretion. None of the other Conditions may be waived. As at the date of this "
     "announcement, none of the Conditions has been fulfilled.",
     "本公司可全權酌情豁免有關賣方所作保證的條件。其他條件概不可獲豁免。於本公告日期，概無條件已獲達"
     "成。"),
    ("p",
     # PLANT 2: 31 December 2026 -> 二零二六年十一月三十日
     "If the Conditions are not fulfilled on or before 31 December 2026 (the \"Long Stop "
     "Date\"), the Agreement shall lapse. Upon the Agreement lapsing, neither party shall "
     "have any claim against the other save for any antecedent breach.",
     "倘條件未能於二零二六年十一月三十日（「最後截止日期」）或之前達成，本協議將告失效。本協議失效後，"
     "任何一方概無權向另一方提出任何申索，惟先前的違約除外。"),
    ("h2", "Completion", "完成"),
    ("p",
     "Completion shall take place on the fifth Business Day after the date on which all the "
     "Conditions have been fulfilled (or waived, as the case may be), or such other date as "
     "the Company and the Vendor may agree in writing.",
     "完成將於所有條件獲達成（或豁免，視情況而定）當日後第五個營業日，或本公司與賣方以書面協定的其他"
     "日期進行。"),
    ("p",
     "Upon Completion, the Target will become a non-wholly owned subsidiary of the Company, "
     "and the financial results of the Target will be consolidated into the consolidated "
     "financial statements of the Group.",
     "完成後，目標公司將成為本公司的非全資附屬公司，而目標公司的財務業績將併入本集團的綜合財務報表。"),

    # ---------------------------------------------------------------- TARGET
    ("h1", "INFORMATION ON THE TARGET", "有關目標公司的資料"),
    ("p",
     "The Target is a company incorporated in Hong Kong with limited liability on 14 March "
     "2011. The Target is principally engaged in the provision of freight forwarding and "
     "warehousing services in Hong Kong. It operates a bonded warehouse of approximately "
     "68,000 square feet in Kwai Chung, maintains a fleet of 24 container trucks and employed "
     "112 full-time staff as at 30 June 2026.",
     "目標公司為一間於二零一一年三月十四日在香港註冊成立的有限公司。目標公司主要於香港從事貨運代理及"
     "倉儲服務。目標公司於葵涌經營一個面積約68,000平方呎的保稅倉庫，擁有24輛貨櫃車的車隊，並於二零二"
     "六年六月三十日僱用112名全職員工。"),
    ("p",
     "The Target also holds the entire equity interest in Harbour Logistics (Shenzhen) "
     "Company Limited, a wholly foreign-owned enterprise established in the PRC with a "
     "registered capital of RMB5,000,000, which provides cross-border trucking services "
     "between Shenzhen and Hong Kong.",
     "目標公司亦持有海港物流（深圳）有限公司的全部股權，該公司為一間於中國成立的外商獨資企業，註冊資"
     "本為人民幣5,000,000元，提供深圳與香港之間的跨境貨運服務。"),
    ("p",
     "Set out below is a summary of the financial information of the Target for the two years "
     "ended 31 December 2025, as extracted from its audited financial statements prepared in "
     "accordance with Hong Kong Financial Reporting Standards.",
     "下文載列目標公司截至二零二五年十二月三十一日止兩個年度的財務資料概要，乃摘錄自其根據香港財務報"
     "告準則編製的經審核財務報表。"),
    ("p",
     "For the year ended 31 December 2024, the Target recorded revenue of approximately "
     "HK$41,600,000, net profit before taxation of approximately HK$2,150,000 and net profit "
     "after taxation of approximately HK$1,790,000.",
     "截至二零二四年十二月三十一日止年度，目標公司錄得收益約港幣4,160萬元、除稅前純利約港幣215萬元及"
     "除稅後純利約港幣179萬元。"),
    ("p",
     "For the year ended 31 December 2025, the Target recorded revenue of approximately "
     "HK$48,200,000. Its net profit before taxation and net profit after taxation for the year "
     "ended 31 December 2025 were approximately HK$3,020,000 and HK$2,520,000 respectively. "
     "Of the revenue of the Target for the year ended 31 December 2025, approximately "
     "RMB9,300,000 (equivalent to approximately HK$10,100,000) was derived from the PRC "
     "subsidiary.",
     "截至二零二五年十二月三十一日止年度，目標公司錄得收益約港幣4,820萬元。其截至二零二五年十二月三十"
     "一日止年度的除稅前純利及除稅後純利分別約為港幣302萬元及港幣252萬元。目標公司截至二零二五年十二月"
     "三十一日止年度的收益中，約人民幣930萬元（相當於約港幣1,010萬元）來自中國附屬公司。"),
    ("p",
     "The unaudited net asset value of the Target as at 30 June 2026 was approximately "
     "HK$16,800,000.",
     "目標公司於二零二六年六月三十日的未經審核資產淨值約為港幣1,680萬元。"),

    # ---------------------------------------------------------------- VENDOR (control swap)
    ("h1", "INFORMATION ON THE VENDOR", "有關賣方的資料"),
    ("p",
     "The Vendor is an investment holding company incorporated in the British Virgin Islands "
     "with limited liability. The Vendor is wholly owned by Mr. Chan Wai Kwong, a "
     "non-executive Director. Mr. Chan has over 25 years of experience in the logistics "
     "industry in Hong Kong and founded the Target in 2011. Save for its shareholding in the "
     "Company and its interest in the Target, the Vendor does not carry on any other business.",
     # CONTROL: sentences 2 and 3 are swapped in Chinese; content identical.
     "賣方為一間於英屬處女群島註冊成立的投資控股有限公司。陳偉光先生於香港物流行業擁有逾25年經驗，並於"
     "二零一一年創立目標公司。賣方由非執行董事陳偉光先生全資擁有。除其於本公司的股權及於目標公司的權益"
     "外，賣方並無經營任何其他業務。"),

    # ---------------------------------------------------------------- GROUP
    ("h1", "INFORMATION ON THE GROUP", "有關本集團的資料"),
    ("p",
     "The Company is an investment holding company incorporated in the Cayman Islands with "
     "limited liability, the Shares of which are listed on the Main Board of the Stock "
     "Exchange. The Group is principally engaged in the trading of building materials, the "
     "provision of supply chain management services and property investment in Hong Kong and "
     "the PRC.",
     "本公司為一間於開曼群島註冊成立的投資控股有限公司，其股份於聯交所主板上市。本集團主要於香港及中國"
     "從事建築材料貿易、提供供應鏈管理服務及物業投資。"),
    ("p",
     "For the six months ended 30 June 2026, the Group recorded unaudited revenue of "
     "approximately HK$186,500,000 and profit attributable to owners of the Company of "
     "approximately HK$9,400,000.",
     "截至二零二六年六月三十日止六個月，本集團錄得未經審核收益約港幣186,500,000元及本公司擁有人應佔溢"
     "利約港幣9,400,000元。"),

    # ---------------------------------------------------------------- REASONS
    ("h1", "REASONS FOR AND BENEFITS OF THE ACQUISITION", "進行收購事項的理由及裨益"),
    ("p",
     "The Group has been providing supply chain management services to customers in the "
     "building materials sector since 2019 and has relied on third-party service providers "
     "for freight forwarding and warehousing. The Board believes that the Acquisition will "
     "allow the Group to internalise these functions, reduce its logistics costs and broaden "
     "the range of services offered to its existing customers.",
     "本集團自二零一九年起一直向建築材料行業的客戶提供供應鏈管理服務，並依賴第三方服務供應商提供貨運"
     "代理及倉儲服務。董事會相信，收購事項將使本集團能夠將該等職能內部化、降低其物流成本，並擴大向現有"
     "客戶提供的服務範圍。"),
    ("p",
     "The Target recorded growth in revenue of approximately 15.9% for the year ended 31 "
     "December 2025 and maintains long-standing relationships with a number of shipping lines "
     "and airline cargo agents.",
     "目標公司截至二零二五年十二月三十一日止年度錄得收益增長約15.9%，並與多家船公司及航空貨運代理保持"
     "長期合作關係。"),
    ("p",
     # PLANT 4: may consider -> 將考慮
     "Following Completion, the Group may consider further acquisitions in the logistics "
     "sector. Any such acquisition will be subject to the applicable requirements of the "
     "Listing Rules and a separate announcement will be made by the Company as and when "
     "appropriate. As at the date of this announcement, the Company has not identified any "
     "specific target and has not entered into any agreement, arrangement or understanding "
     "in respect of any such acquisition.",
     "完成後，本集團將考慮於物流行業進行進一步收購。任何該等收購將須遵守上市規則的適用規定，本公司將"
     "於適當時候另行刊發公告。於本公告日期，本公司尚未物色任何特定目標，亦未就任何該等收購訂立任何協"
     "議、安排或諒解。"),
    ("p",
     "The Directors (other than the independent non-executive Directors, whose views will be "
     "set out in the circular after considering the advice of the Independent Financial "
     "Adviser) are of the view that the terms of the Agreement are on normal commercial terms, "
     "fair and reasonable and in the interests of the Company and the Shareholders as a whole.",
     "董事（獨立非執行董事除外，彼等的意見將於考慮獨立財務顧問的意見後載於通函內）認為，本協議的條款"
     "屬一般商業條款，公平合理，並符合本公司及股東的整體利益。"),
    ("p",
     "Mr. Chan Wai Kwong, who is interested in the Acquisition through his interest in the "
     "Vendor, has abstained from voting on the relevant Board resolution. Save as disclosed "
     "above, none of the Directors has a material interest in the Acquisition.",
     "陳偉光先生因其於賣方的權益而於收購事項中擁有權益，故已就相關董事會決議案放棄投票。除上文所披露"
     "者外，概無董事於收購事項中擁有重大權益。"),

    # ---------------------------------------------------------------- LISTING RULES
    ("h1", "LISTING RULES IMPLICATIONS", "上市規則的涵義"),
    ("p",
     "As one or more of the applicable percentage ratios (as defined under Rule 14.07 of the "
     "Listing Rules) in respect of the Acquisition exceed 5% but all of them are less than "
     "25%, the Acquisition constitutes a discloseable transaction of the Company under "
     "Chapter 14 of the Listing Rules and is subject to the reporting and announcement "
     "requirements under Chapter 14 of the Listing Rules. The highest applicable percentage "
     "ratio in respect of the Acquisition is approximately 6.8%.",
     "由於收購事項的一項或多項適用百分比率（定義見上市規則第14.07條）超過5%但全部均低於25%，故收購事"
     "項構成上市規則第14章項下本公司的一項須予披露交易，並須遵守上市規則第14章項下的申報及公告規定。"
     "收購事項的最高適用百分比率約為6.8%。"),
    ("p",
     "As at the date of this announcement, the Vendor holds 412,500,000 Shares, representing "
     "approximately 18.75% of the issued share capital of the Company, and is therefore a "
     "substantial shareholder of the Company and a connected person of the Company under "
     "Chapter 14A of the Listing Rules. Accordingly, the Acquisition also constitutes a "
     "connected transaction of the Company and is subject to the reporting, announcement, "
     "circular and Independent Shareholders' approval requirements under Chapter 14A of the "
     "Listing Rules.",
     "於本公告日期，賣方持有412,500,000股股份，佔本公司已發行股本約18.75%，因此為本公司的主要股東及上"
     "市規則第14A章項下本公司的關連人士。因此，收購事項亦構成本公司的一項關連交易，並須遵守上市規則第"
     "14A章項下的申報、公告、通函及獨立股東批准規定。"),
    ("p",
     "An Independent Board Committee comprising all the independent non-executive Directors, "
     "namely Mr. Ho Kam Fai, Dr. Leung Mei Yee and Mr. Ng Chun Yin, has been established to "
     "advise the Independent Shareholders on the terms of the Agreement and the Acquisition. "
     "Crestview Capital Limited has been appointed as the Independent Financial Adviser to "
     "advise the Independent Board Committee and the Independent Shareholders in this regard.",
     "本公司已成立由全體獨立非執行董事（即何錦輝先生、梁美儀博士及吳俊賢先生）組成的獨立董事委員會，"
     "以就本協議及收購事項的條款向獨立股東提供意見。本公司已委任峰景資本有限公司為獨立財務顧問，以就"
     "此向獨立董事委員會及獨立股東提供意見。"),

    # ---------------------------------------------------------------- EGM
    ("h1", "EGM", "股東特別大會"),
    ("p",
     "The EGM will be convened and held for the Independent Shareholders to consider and, if "
     "thought fit, approve the Agreement and the transactions contemplated thereunder. The "
     "Vendor, Mr. Chan Wai Kwong and their respective associates, who together hold "
     "412,500,000 Shares as at the date of this announcement, will abstain from voting on the "
     "resolution to be proposed at the EGM.",
     "本公司將召開及舉行股東特別大會，以供獨立股東考慮及酌情批准本協議及其項下擬進行的交易。賣方、陳"
     "偉光先生及彼等各自的聯繫人（於本公告日期合共持有412,500,000股股份）將就股東特別大會上提呈的決議"
     "案放棄投票。"),
    ("p",
     "To the best of the Directors' knowledge, information and belief, having made all "
     "reasonable enquiries, no other Shareholder has a material interest in the Acquisition "
     "and is required to abstain from voting at the EGM.",
     "據董事經作出一切合理查詢後所深知、盡悉及確信，概無其他股東於收購事項中擁有重大權益而須於股東特"
     "別大會上放棄投票。"),
    ("p",
     "A circular containing, among other things, further details of the Agreement, the "
     "recommendation of the Independent Board Committee, the letter of advice from the "
     "Independent Financial Adviser, the valuation report on the Target and a notice "
     "convening the EGM is expected to be despatched to the Shareholders on or before 15 "
     "October 2026. The EGM is expected to be held on or before 6 November 2026.",
     "一份載有（其中包括）本協議的進一步詳情、獨立董事委員會的推薦意見、獨立財務顧問的意見函件、目標"
     "公司的估值報告及召開股東特別大會的通告的通函，預期將於二零二六年十月十五日或之前寄發予股東。股東"
     "特別大會預期將於二零二六年十一月六日或之前舉行。"),

    # ---------------------------------------------------------------- GENERAL
    ("h1", "GENERAL", "一般資料"),
    ("p",
     "The Acquisition is subject to the fulfilment of the Conditions and may or may not "
     "proceed. Shareholders and potential investors should exercise caution when dealing in "
     "the Shares.",
     "收購事項須待條件達成後方可進行，因此可能會或可能不會進行。股東及潛在投資者於買賣股份時務請審慎"
     "行事。"),
    ("p",
     "This announcement is made in both English and Chinese. In the event of any "
     "inconsistency, the English version of this announcement shall prevail.",
     "本公告以中英文兩種語言刊發。本公告中英文版本如有歧義，概以英文版本為準。"),

    # ---------------------------------------------------------------- DEFINITIONS
    ("h1", "DEFINITIONS", "釋義"),
    ("p",
     "In this announcement, unless the context otherwise requires, the following expressions "
     "shall have the following meanings:",
     "於本公告內，除文義另有所指外，下列詞語具有以下涵義："),
]

DEFINITIONS = [
    ("Acquisition", "the acquisition of the Sale Shares by the Company from the Vendor pursuant to the Agreement",
     "收購事項", "本公司根據本協議向賣方收購銷售股份"),
    ("Agreement", "the conditional sale and purchase agreement dated 23 September 2026 entered into between the Company and the Vendor in relation to the Acquisition",
     "本協議", "本公司與賣方就收購事項於二零二六年九月二十三日訂立的有條件買賣協議"),
    ("associate(s)", "has the meaning ascribed to it under the Listing Rules",
     "聯繫人", "具有上市規則所賦予的涵義"),
    ("Board", "the board of Directors", "董事會", "董事會"),
    ("Business Day", "a day (other than a Saturday, Sunday or public holiday) on which licensed banks in Hong Kong are generally open for business",
     "營業日", "香港持牌銀行一般開門營業的日子（星期六、星期日或公眾假期除外）"),
    ("Company", "Meridian Pacific Holdings Limited, a company incorporated in the Cayman Islands with limited liability, the Shares of which are listed on the Main Board of the Stock Exchange (stock code: 1877)",
     "本公司", "明源太平洋控股有限公司，一間於開曼群島註冊成立的有限公司，其股份於聯交所主板上市（股份代號：1877）"),
    ("Completion", "completion of the Acquisition in accordance with the terms of the Agreement",
     "完成", "根據本協議的條款完成收購事項"),
    ("Conditions", "the conditions precedent to Completion as set out in the Agreement",
     "條件", "本協議所載完成的先決條件"),
    ("connected person(s)", "has the meaning ascribed to it under the Listing Rules",
     "關連人士", "具有上市規則所賦予的涵義"),
    ("Consideration", "the consideration payable by the Company for the Sale Shares under the Agreement",
     "代價", "本公司根據本協議就銷售股份應付的代價"),
    ("Director(s)", "the director(s) of the Company", "董事", "本公司董事"),
    ("EGM", "the extraordinary general meeting of the Company to be convened and held to consider and, if thought fit, approve the Agreement and the transactions contemplated thereunder",
     "股東特別大會", "本公司將召開及舉行以考慮及酌情批准本協議及其項下擬進行的交易的股東特別大會"),
    ("Group", "the Company and its subsidiaries", "本集團", "本公司及其附屬公司"),
    ("HK$", "Hong Kong dollars, the lawful currency of Hong Kong", "港幣", "香港法定貨幣港元"),
    ("Hong Kong", "the Hong Kong Special Administrative Region of the PRC", "香港", "中國香港特別行政區"),
    ("Independent Board Committee", "the independent committee of the Board comprising all the independent non-executive Directors, established to advise the Independent Shareholders in respect of the Agreement and the Acquisition",
     "獨立董事委員會", "由全體獨立非執行董事組成，以就本協議及收購事項向獨立股東提供意見的董事會獨立委員會"),
    ("Independent Financial Adviser", "Crestview Capital Limited, a corporation licensed to carry out Type 1 (dealing in securities) and Type 6 (advising on corporate finance) regulated activities under the SFO, being the independent financial adviser appointed to advise the Independent Board Committee and the Independent Shareholders",
     "獨立財務顧問", "峰景資本有限公司，一間根據證券及期貨條例可進行第1類（證券交易）及第6類（就機構融資提供意見）受規管活動的持牌法團，為獲委任以向獨立董事委員會及獨立股東提供意見的獨立財務顧問"),
    ("Independent Shareholders", "Shareholders other than the Vendor, Mr. Chan Wai Kwong and their respective associates",
     "獨立股東", "除賣方、陳偉光先生及彼等各自的聯繫人以外的股東"),
    ("Independent Third Party(ies)", "person(s) or company(ies) which, to the best of the Directors' knowledge, information and belief, having made all reasonable enquiries, are independent of and not connected with the Company and its connected persons",
     "獨立第三方", "據董事經作出一切合理查詢後所深知、盡悉及確信，獨立於本公司及其關連人士且與彼等概無關連的人士或公司"),
    ("Listing Rules", "the Rules Governing the Listing of Securities on the Stock Exchange",
     "上市規則", "聯交所證券上市規則"),
    ("Long Stop Date", "31 December 2026, or such later date as the Company and the Vendor may agree in writing",
     "最後截止日期", "二零二六年十二月三十一日，或本公司與賣方以書面協定的較後日期"),
    ("PRC", "the People's Republic of China, which for the purpose of this announcement excludes Hong Kong, the Macau Special Administrative Region and Taiwan",
     "中國", "中華人民共和國，就本公告而言，不包括香港、澳門特別行政區及台灣"),
    ("RMB", "Renminbi, the lawful currency of the PRC", "人民幣", "中國法定貨幣人民幣"),
    ("Sale Shares", "6,000 ordinary shares in the Target, representing 60% of its entire issued share capital",
     "銷售股份", "目標公司6,000股普通股，相當於其全部已發行股本的60%"),
    ("SFO", "the Securities and Futures Ordinance (Chapter 571 of the Laws of Hong Kong)",
     "證券及期貨條例", "香港法例第571章證券及期貨條例"),
    ("Share(s)", "ordinary share(s) of HK$0.01 each in the share capital of the Company",
     "股份", "本公司股本中每股面值港幣0.01元的普通股"),
    ("Shareholder(s)", "holder(s) of the Share(s)", "股東", "股份持有人"),
    ("Stock Exchange", "The Stock Exchange of Hong Kong Limited", "聯交所", "香港聯合交易所有限公司"),
    ("substantial shareholder", "has the meaning ascribed to it under the Listing Rules",
     "主要股東", "具有上市規則所賦予的涵義"),
    ("Target", "Harbour Logistics Limited, a company incorporated in Hong Kong with limited liability",
     "目標公司", "海港物流有限公司，一間於香港註冊成立的有限公司"),
    ("Vendor", "Golden Anchor Investments Limited, a company incorporated in the British Virgin Islands with limited liability",
     "賣方", "金錨投資有限公司，一間於英屬處女群島註冊成立的有限公司"),
    ("%", "per cent", "%", "百分比"),
]

for _en_t, _en_m, _zh_t, _zh_m in DEFINITIONS:
    _verb = "" if _en_m.startswith("has the meaning") else "means "
    DOC.append(("p", f"\"{_en_t}\" {_verb}{_en_m}", f"「{_zh_t}」{'' if _zh_m.startswith('具有') else '指'}{_zh_m}"))

DOC += [
    # Extra Chinese-only sub-heading -> one unaligned section.
    ("zh_h2", None, "釋義補充"),
    ("zh_p", None, "本公告內若干公司及人士的中文名稱僅為其英文名稱的譯名，僅供識別之用。"),
    ("gap", 14),
    ("sig_c", "By order of the Board", "承董事會命"),
    ("sig_c", "Meridian Pacific Holdings Limited", "明源太平洋控股有限公司"),
    ("sig_c", "Lau Chi Ming", "主席兼執行董事"),
    ("sig_c", "Chairman and Executive Director", "劉志明"),
    ("gap", 10),
    ("p", "Hong Kong, 24 September 2026", "香港，二零二六年九月二十四日"),
    ("p",
     "As at the date of this announcement, the executive Directors are Mr. Lau Chi Ming and "
     "Ms. Wong Siu Lan; the non-executive Director is Mr. Chan Wai Kwong; and the independent "
     "non-executive Directors are Mr. Ho Kam Fai, Dr. Leung Mei Yee and Mr. Ng Chun Yin.",
     "於本公告日期，執行董事為劉志明先生及黃小蘭女士；非執行董事為陳偉光先生；及獨立非執行董事為何錦"
     "輝先生、梁美儀博士及吳俊賢先生。"),
]

# --------------------------------------------------------------------------
# Answer key
# --------------------------------------------------------------------------

PLANTS = [
    {"plant": 1, "type": "NUMBER_MISMATCH", "expected_severity": "Critical",
     "section": "THE ACQUISITION AGREEMENT — Consideration",
     "en_snippet": "The Consideration is HK$12.4 million, payable in cash on Completion.",
     "zh_snippet": "代價為港幣1,210萬元，於完成時以現金支付。",
     "note": "HK$12.4 million in English; HK$12.1 million (1,210萬) in Chinese."},
    {"plant": 2, "type": "DATE_MISMATCH", "expected_severity": "Critical",
     "section": "THE ACQUISITION AGREEMENT — Conditions precedent",
     "en_snippet": "If the Conditions are not fulfilled on or before 31 December 2026 (the \"Long Stop Date\"), the Agreement shall lapse.",
     "zh_snippet": "倘條件未能於二零二六年十一月三十日（「最後截止日期」）或之前達成，本協議將告失效。",
     "note": "Long stop date 31 December 2026 in English; 30 November 2026 in Chinese."},
    {"plant": 3, "type": "OMISSION_MATERIAL", "expected_severity": "Critical",
     "section": "THE ACQUISITION AGREEMENT — Conditions precedent",
     "en_snippet": "(c) the Independent Shareholders having approved the Acquisition at the EGM.",
     "zh_snippet": "(b) 賣方已就收購事項取得所有必要的第三方同意；",
     "note": "Condition (c) is absent from the Chinese list, which is relettered (a)(b)(c). zh_snippet is the nearest neighbour."},
    {"plant": 4, "type": "HEDGE_CHANGE", "expected_severity": "Material",
     "section": "REASONS FOR AND BENEFITS OF THE ACQUISITION",
     "en_snippet": "Following Completion, the Group may consider further acquisitions in the logistics sector.",
     "zh_snippet": "完成後，本集團將考慮於物流行業進行進一步收購。",
     "note": "may consider (conditional) became 將考慮 (definite)."},
    {"plant": 5, "type": "MEANING_SHIFT", "expected_severity": "Material",
     "section": "THE ACQUISITION AGREEMENT — Consideration",
     "en_snippet": "The Company shall procure the payment of the Consideration from its internal resources.",
     "zh_snippet": "本集團須以內部資源促使支付代價。",
     "note": "Obligation sits with the Company in English but the Group (本集團) in Chinese."},
]

CONTROL = {
    "plant": 6, "type": "CONTROL", "expected_severity": None,
    "section": "INFORMATION ON THE VENDOR",
    "en_snippet": "The Vendor is wholly owned by Mr. Chan Wai Kwong, a non-executive Director. Mr. Chan has over 25 years of experience in the logistics industry in Hong Kong and founded the Target in 2011.",
    "zh_snippet": "陳偉光先生於香港物流行業擁有逾25年經驗，並於二零一一年創立目標公司。賣方由非執行董事陳偉光先生全資擁有。",
    "note": "Two adjacent sentences appear in swapped order in Chinese; content identical. Must NOT be flagged.",
}

UNALIGNED = {"lang": "zh", "heading": "釋義補充",
             "zh_snippet": "本公告內若干公司及人士的中文名稱僅為其英文名稱的譯名，僅供識別之用。",
             "note": "Chinese-only sub-heading near the end; expected to surface as one unaligned section."}

# --------------------------------------------------------------------------
# Layout engine
# --------------------------------------------------------------------------

ZH_TOKEN = re.compile(r"[0-9A-Za-z][0-9A-Za-z,.%$]*|.")
ZH_NO_START = set("，。、；：」』）！？％%）)]}")
ZH_NO_END = set("「『（([{")


class Writer:
    def __init__(self, lang):
        self.lang = lang
        self.body_font = FONTS[lang]["body"]
        self.head_font = FONTS[lang]["head"]
        self.lead = FONTS[lang]["lead"]
        self.doc = pymupdf.open()
        self.page = None
        self.y = 0.0
        self._fonts = {}
        self.new_page()

    # -- fonts / measuring
    def font(self, name):
        if name not in self._fonts:
            self._fonts[name] = pymupdf.Font(name)
        return self._fonts[name]

    def width(self, text, fontname, size):
        return self.font(fontname).text_length(text, fontsize=size)

    # -- pages
    def new_page(self):
        if self.page is not None:
            self._footer()
        self.page = self.doc.new_page(width=PAGE_W, height=PAGE_H)
        self.y = MARGIN

    def _footer(self):
        label = f"- {self.page.number + 1} -"
        w = self.width(label, "helv", 9)
        self.page.insert_text(((PAGE_W - w) / 2, PAGE_H - 32), label, fontname="helv", fontsize=9)

    def ensure(self, height):
        if self.y + height > PAGE_H - MARGIN:
            self.new_page()

    # -- primitive: one line of text at the current y
    def line(self, text, fontname, size, lead, x=MARGIN, center=False):
        self.ensure(lead)
        if center:
            x = MARGIN + (TEXT_W - self.width(text, fontname, size)) / 2
        baseline = self.y + size * 0.8
        if all(ord(c) < 256 for c in text) and fontname in ("helv", "hebo"):
            self.page.insert_text((x, baseline), text, fontname=fontname, fontsize=size)
        else:
            tw = pymupdf.TextWriter(self.page.rect)
            tw.append((x, baseline), text, font=self.font(fontname), fontsize=size)
            tw.write_text(self.page)
        self.y += lead

    # -- wrapping
    def wrap(self, text, fontname, size, width):
        if self.lang == "zh":
            return self._wrap_zh(text, fontname, size, width)
        return self._wrap_en(text, fontname, size, width)

    def _wrap_en(self, text, fontname, size, width):
        lines, cur = [], ""
        for word in text.split(" "):
            trial = word if not cur else f"{cur} {word}"
            if self.width(trial, fontname, size) <= width:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
        return lines

    def _wrap_zh(self, text, fontname, size, width):
        tokens = ZH_TOKEN.findall(text)
        lines, cur = [], ""
        for tok in tokens:
            trial = cur + tok
            if self.width(trial, fontname, size) <= width or not cur:
                cur = trial
            elif tok in ZH_NO_START:
                cur = trial                      # allow a closing mark to overhang slightly
            else:
                # do not leave an opening bracket dangling at the end of a line
                if cur and cur[-1] in ZH_NO_END:
                    lines.append(cur[:-1])
                    cur = cur[-1] + tok
                else:
                    lines.append(cur)
                    cur = tok
        lines.append(cur)
        return [l for l in lines if l]

    # -- block-level helpers
    def paragraph(self, text, size=BODY, fontname=None, lead=None, x=MARGIN, width=TEXT_W,
                  hang=0.0, center=False, after=8.0):
        fontname = fontname or self.body_font
        lead = lead or self.lead
        lines = self.wrap(text, fontname, size, width - hang)
        # keep at least two lines together at a page break
        self.ensure(min(len(lines), 2) * lead)
        for i, ln in enumerate(lines):
            self.line(ln, fontname, size, lead, x=x + (hang if i else 0), center=center)
        self.y += after

    def heading(self, text, size=HEAD, before=12.0, after=5.0):
        self.ensure(before + size * 1.5 + 2 * self.lead)   # keep heading with next lines
        self.y += before
        for ln in self.wrap(text, self.head_font, size, TEXT_W):
            self.line(ln, self.head_font, size, size * 1.45)
        self.y += after

    def list_block(self, lead_text, items):
        """Lead-in sentence and items with normal line spacing so they form one block."""
        lines = self.wrap(lead_text, self.body_font, BODY, TEXT_W)
        self.ensure((len(lines) + 2) * self.lead)
        for ln in lines:
            self.line(ln, self.body_font, BODY, self.lead)
        for item in items:
            # marker stays inside the first line's text so "(b) ..." is verbatim in the text layer
            body_lines = self.wrap(item, self.body_font, BODY, TEXT_W - 28)
            for i, ln in enumerate(body_lines):
                self.line(ln, self.body_font, BODY, self.lead, x=MARGIN + (28 if i else 0))
        self.y += 8

    def save(self, path):
        self._footer()
        self.doc.save(path, garbage=3, deflate=True)
        self.doc.close()


def build(lang, path):
    w = Writer(lang)
    idx = 1 if lang == "en" else 2
    for item in DOC:
        kind = item[0]
        if kind == "gap":
            w.y += item[1]
            continue
        if kind == "list":
            _, en_lead, zh_lead, en_items, zh_items = item
            w.list_block(en_lead if lang == "en" else zh_lead, en_items if lang == "en" else zh_items)
            continue
        text = item[idx]
        if text is None:
            continue
        if kind == "disc":
            w.paragraph(text, size=SMALL, lead=SMALL * 1.4, after=4)
        elif kind == "cname":
            w.paragraph(text, size=HEAD, fontname=w.head_font, lead=HEAD * 1.45, center=True, after=2)
        elif kind == "cline":
            w.paragraph(text, center=True, after=1)
        elif kind == "title":
            w.paragraph(text, size=TITLE, fontname=w.head_font, lead=TITLE * 1.4, center=True, after=6)
        elif kind in ("h1", "zh_h2"):
            w.heading(text)
        elif kind == "h2":
            w.heading(text, before=8.0)
        elif kind == "sig_c":
            w.paragraph(text, center=True, after=0)
        else:  # p, zh_p
            w.paragraph(text)
    w.save(path)


def write_answer_key(path):
    key = {
        "pair": {"en": "data/sample/en.pdf", "zh": "data/sample/zh.pdf", "authoritative": "EN"},
        "company": "Meridian Pacific Holdings Limited", "stock_code": "1877",
        "en_title": EN_TITLE, "zh_title": ZH_TITLE,
        "expected_findings": PLANTS,
        "control": CONTROL,
        "unaligned_sections": [UNALIGNED],
        "notes": [
            "Only the five planted findings above are genuine discrepancies; the control must read as EQUIVALENT.",
            "Cosmetic FORMAT/WORDING findings such as HK$48,200,000 vs 港幣4,820萬元 are acceptable noise, not errors.",
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(key, f, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------

def verify():
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("  PASS  " if cond else "  FAIL  ") + msg)
        ok = ok and cond

    texts, docs = {}, {}
    for lang in ("en", "zh"):
        d = pymupdf.open(os.path.join(OUT_DIR, f"{lang}.pdf"))
        docs[lang] = d
        raw = "".join(p.get_text() for p in d)
        # our wrapper never breaks inside words/numbers; joining lines restores the sentences
        texts[lang] = re.sub(r"[ \n]+", " ", raw) if lang == "en" else raw.replace("\n", "")
        print(f"{lang}.pdf: {d.page_count} pages")

    print("\nPlanted sentences present verbatim:")
    for p in PLANTS + [CONTROL]:
        check(p["en_snippet"] in texts["en"], f"EN plant {p['plant']}: {p['en_snippet'][:60]}...")
        check(p["zh_snippet"] in texts["zh"], f"ZH plant {p['plant']}: {p['zh_snippet'][:30]}...")
    check(UNALIGNED["heading"] in texts["zh"], "ZH-only heading 釋義補充 present")
    check(UNALIGNED["heading"] not in texts["en"], "釋義補充 absent from EN")

    print("\nFixture sentences (fixtures/findings.json) present verbatim:")
    with open(os.path.join(ROOT, "fixtures", "findings.json"), encoding="utf-8") as f:
        fx = json.load(f)
    for fnd in fx["findings"]:
        check(fnd["en"]["text"] in texts["en"], f"{fnd['id']} EN")
        check(fnd["zh"]["text"] in texts["zh"], f"{fnd['id']} ZH")
    check(EN_TITLE in texts["en"], "EN title with em dash")
    check(ZH_TITLE in texts["zh"], "ZH title")

    print("\nConsideration figure:")
    check("港幣1,210萬元" in texts["zh"], "ZH contains 港幣1,210萬元")
    check("港幣1,240萬元" not in texts["zh"], "ZH does not contain 港幣1,240萬元")
    check("HK$12.4 million" in texts["en"], "EN contains HK$12.4 million")
    check("(c) the Independent Shareholders" in texts["en"] and "獨立股東已於股東特別大會" not in texts["zh"],
          "condition (c) only in EN")
    check(texts["zh"].count("(c) 賣方根據本協議") == 1 and "(d) " not in texts["zh"], "ZH list relettered (a)(b)(c)")

    print("\nFont sizes:")
    for lang, d in docs.items():
        sizes, heads = [], {}
        for page in d:
            for b in page.get_text("dict")["blocks"]:
                for l in b.get("lines", []):
                    for s in l["spans"]:
                        sizes.append(round(s["size"], 2))
                        if s["size"] > 12:
                            heads.setdefault(round(s["size"], 2), []).append(s["text"])
        sizes.sort()
        median = sizes[len(sizes) // 2]
        print(f"  {lang}: body median {median}, heading sizes {sorted(heads)}, "
              f"ratio {min(heads) / median:.3f}")
        check(min(heads) > 1.15 * median, f"{lang}: heading size > 1.15 x body median")
        check(sum(1 for t in heads.get(13.0, []) if t.strip() in
                  ("INTRODUCTION", "GENERAL", "DEFINITIONS", "緒言", "一般資料", "釋義")) >= 3,
              f"{lang}: h1 headings rendered at 13pt")

    print("\nPage previews (first 300 chars):")
    for lang, d in docs.items():
        for page in d:
            preview = page.get_text().replace("\n", " ")[:300]
            print(f"--- {lang} p.{page.number + 1} ---\n{preview}\n")

    print("VERIFY:", "ALL PASS" if ok else "FAILURES PRESENT")
    return ok


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    if "--verify" not in sys.argv:
        build("en", os.path.join(OUT_DIR, "en.pdf"))
        build("zh", os.path.join(OUT_DIR, "zh.pdf"))
        write_answer_key(os.path.join(OUT_DIR, "answer_key.json"))
        print("wrote", OUT_DIR, "en.pdf zh.pdf answer_key.json")
    sys.exit(0 if verify() else 1)


if __name__ == "__main__":
    main()
