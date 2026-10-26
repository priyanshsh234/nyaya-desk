"""Parser tests.

`cnr_DLND020000602007_partial.html` is real portal output (see header
comment in the fixture). The smaller inline snippets cover sections that the
real capture did not include (hearing history, orders, case lists); they
follow the same markup conventions and test the generic handling.
"""
from pathlib import Path

from app.ecourts import parser

FIX = Path(__file__).parent / "fixtures"


def test_real_cnr_fragment():
    html = (FIX / "cnr_DLND020000602007_partial.html").read_text(encoding="utf-8")
    case = parser.parse_case_detail(html)

    assert case["court_name"] == "Chief Metropolitan Magistrate, New Delhi, PHC"
    cd = case["case_details"]
    assert cd["case_type"] == "Cr Cases - CRIMINAL CASE"
    assert cd["filing_number"] == "72464/2007"
    assert cd["filing_date"] == "18-09-2007"
    assert cd["registration_number"] == "39932/2016"
    assert cd["cnr_number"] == "DLND020000602007"  # nag note stripped
    assert cd["e_filing_date"] == "-"

    cs = case["case_status"]
    assert cs["next_hearing_date"] == "27th October 2026"
    assert cs["case_stage"] == "Prosecution Evidence"
    assert cs["court_number_and_judge"].startswith("39-Judicial Magistrate")

    # Parties come from <ul> lists, not tables.
    assert [p["name"] for p in case["petitioners"]] == ["STATE"]
    assert [p["name"] for p in case["respondents"]] == ["MOHINDER PAL SINGH ETC (2)", "JASWINDER SINGH"]
    assert case["title"] == "STATE vs MOHINDER PAL SINGH ETC (2), JASWINDER SINGH"

    assert case["acts"] == []  # header-only table
    assert case["orders"] == []  # 'border' class must not be mistaken for orders


def test_parties_with_advocates():
    html = """<h3>Petitioner and Advocate</h3>
    <ul class='Petitioner_Advocate_table'><li>1) Punjab National Bank<br>
    Advocate- Rajesh Kumar<br>2) Branch Manager PNB<br>Saket, New Delhi</li></ul>"""
    case = parser.parse_case_detail(html)
    pet = case["petitioners"]
    assert pet[0]["name"] == "Punjab National Bank"
    assert pet[0]["advocate"] == "Rajesh Kumar"
    assert pet[1]["name"] == "Branch Manager PNB"
    assert pet[1]["details"] == "Saket, New Delhi"


def test_history_and_orders():
    html = """
    <h3>Case History</h3>
    <table class="table history_table table-bordered">
      <tr><th>Judge</th><th>Business on Date</th><th>Hearing Date</th><th>Purpose of hearing</th></tr>
      <tr><td>DJ-01</td><td><a href='#' onclick="viewBusiness('3','8','28-11-2024','201600002332024','26','','12-08-2024','1','DLST01','cnr','1')">12-08-2024</a></td>
          <td>28-11-2024</td><td>Appearance</td></tr>
    </table>
    <h3>Interim Orders</h3>
    <table class="table order_table table-bordered">
      <tr><td>Order Number</td><td>Order Date</td><td>Order Details</td></tr>
      <tr><td>1</td><td>12-08-2024</td><td><a onclick="displayPdf('normal_v=1&case_val=CS~233~2024&court_code=3&filename=/orders/2024/x.pdf&appFlag=')">Copy of order</a></td></tr>
    </table>
    <h3>Final Orders / Judgements</h3>
    <table class="table order_table">
      <tr><th>Order Number</th><th>Order Date</th><th>Order Details</th></tr>
      <tr><td>2</td><td>01-02-2025</td><td><a onclick="displayPdf(1,'CS~233~2024','3','/orders/2025/y.pdf','')">Judgement</a></td></tr>
    </table>"""
    case = parser.parse_case_detail(html)

    h = case["hearing_history"][0]
    assert h["purpose_of_hearing"] == "Appearance"
    assert h["business_args"]["nextdate1"] == "28-11-2024"
    assert h["business_args"]["srno"] == "1"

    interim, final = case["orders"]
    assert interim["type"] == "interim"
    assert interim["pdf_args"]["filename"] == "/orders/2024/x.pdf"  # query-string form
    assert final["type"] == "final"
    assert final["pdf_args"]["filename"] == "/orders/2025/y.pdf"  # positional form


def test_case_list():
    html = """<table><tr><th>Sr No</th><th>Case Type/Case Number/Case Year</th>
      <th>Petitioner Name versus Respondent Name</th><th>View</th></tr>
      <tr><td colspan=3>District and Sessions Judge, South , Saket</td></tr>
      <tr><td>1</td><td>CS (COMM)/233/2024</td><td>Punjab National Bank<br>Vs<br>Sunil Kumar</td>
      <td><a href='#' onClick="viewHistory(201600002332024,'DLST010012342024',3,'','CScaseNumber',26,8,'1080010','CScaseNumber')">View</a></td></tr>
    </table>"""
    [row] = parser.parse_case_list(html)
    assert row["petitioner"] == "Punjab National Bank"
    assert row["respondent"] == "Sunil Kumar"
    assert row["establishment"] == "District and Sessions Judge, South , Saket"
    assert row["view_args"]["cino"] == "DLST010012342024"
    assert row["view_args"]["court_complex_code"] == "1080010"


def test_options_and_complex():
    opts = parser.parse_options("<option value='0'>Select district</option><option value='8'>South</option>")
    assert opts == [{"value": "8", "label": "South"}]
    cx = parser.parse_complex_value("1080010@1,2@Y")
    assert cx == {"complex_code": "1080010", "establishment_codes": ["1", "2"], "requires_establishment": True}


def test_not_found_detection():
    assert parser.looks_not_found("<span>This Case Code does not exists</span>")
    assert parser.looks_not_found("<table><tr><td>x</td></tr></table>") is None
