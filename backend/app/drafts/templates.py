"""The draft templates themselves.

Each template is a plain function `build(values) -> Draft` plus a field
schema. Templates are written as straight-line Python rather than a
text-template language (Jinja etc.) because legal drafts are full of
conditional prose -- singular/plural parties, optional paragraphs, computed
limitation/custody periods -- which is clearer as code than as `{% if %}`
soup, and keeps the "pure Python, no external services" constraint obvious.

Statutory references follow the law in force: criminal procedure cites the
Bharatiya Nagarik Suraksha Sanhita, 2023 (BNSS), which replaced the CrPC for
proceedings from 1 July 2024. Each template's output is a starting draft for
a lawyer to review, not a finished pleading -- the UI says so explicitly.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from .engine import BLANK, DocBuilder, Draft, FieldSpec, Template
from .textutils import (
    join_names, long_date, paragraphs, role, rupees, short_date, that_clause, verb,
)

# ----------------------------------------------------------------- helpers


def _party_block(b: DocBuilder, parties: list[dict], label: str) -> None:
    """Cause-title party listing:

        1. ABC Traders Pvt. Ltd.
           Registered office at ...
                                             ...PLAINTIFF NO. 1
    Numbered only when there is more than one party, as courts expect.
    """
    multi = len(parties) > 1
    for i, p in enumerate(parties, 1):
        b.left(f"{i}. {p['name']}" if multi else p["name"], bold=True)
        if p.get("details"):
            b.left(p["details"])
        b.right(f"...{label.upper()}" + (f" NO. {i}" if multi else ""), bold=True)


def _names(parties: list[dict]) -> str:
    return join_names([p["name"] for p in parties])


def _pct(rate) -> str:
    return f"{Decimal(str(rate)).normalize():f}% per annum"


COMMON_ADVOCATE = [
    FieldSpec("advocate_name", "Advocate name", group="Advocate", placeholder="e.g. Adv. Priya Sharma"),
    FieldSpec("advocate_enrolment", "Enrolment no.", required=False, group="Advocate",
              placeholder="e.g. D/1234/2015"),
    FieldSpec("advocate_address", "Chamber / office address", type="textarea", required=False,
              group="Advocate"),
]


def _signature(b: DocBuilder, v: dict, for_whom: str) -> None:
    b.space()
    b.right(for_whom, bold=True)
    b.right("THROUGH")
    b.right(v["advocate_name"], bold=True)
    if v.get("advocate_enrolment"):
        b.right(f"Enrolment No. {v['advocate_enrolment']}")
    if v.get("advocate_address"):
        b.right(v["advocate_address"])
    b.left(f"Place: {v.get('place') or BLANK}")
    b.left(f"Date: {short_date(v['date']) if v.get('date') else BLANK}")


# ============================================================ legal notice


def build_legal_notice(v: dict) -> Draft:
    b = DocBuilder()
    warnings: list[str] = []
    recipients = v["recipients"]
    n = len(recipients)
    you = "you" if n == 1 else "you all"

    if v.get("advocate_address"):
        b.center(v["advocate_name"], bold=True).center(v["advocate_address"])
        b.space()
    b.left(f"By {v['mode']}")
    b.right(f"Date: {short_date(v['date'])}")
    b.title("Legal Notice")
    b.left("To,", bold=True)
    for i, r in enumerate(recipients, 1):
        b.left((f"{i}. " if n > 1 else "") + r["name"], bold=True)
        if r.get("details"):
            b.left(r["details"])
    b.space()
    amount = rupees(v["amount_due"])
    subject = v.get("subject") or f"Legal notice for recovery of {amount}"
    b.para(f"Subject: {subject}", bold=True)
    b.para("Sir/Madam," if n == 1 else "Sirs/Madams,")
    client = v["client_name"] + (f", {v['client_details']}" if v.get("client_details") else "")
    b.para(f"Under instructions from and on behalf of my client, {client} (hereinafter referred "
           f"to as \"my client\"), I hereby serve upon {you} the following legal notice:")

    for fact in paragraphs(v["facts"]):
        b.numbered(that_clause(fact))

    since = f" since {short_date(v['due_since'])}" if v.get("due_since") else ""
    b.numbered(f"That a sum of {amount} is lawfully due and payable by {you} to my client{since}. "
               f"Despite repeated requests and reminders, {you} {verb('has', 'have', n)} failed and "
               f"neglected to pay the said amount, which shows your "
               "malafide intention to wrongfully withhold the money of my client.")

    interest = ""
    if v.get("interest_rate"):
        start = short_date(v["due_since"]) if v.get("due_since") else "the date it fell due"
        interest = f", together with interest at the rate of {_pct(v['interest_rate'])} from {start} till the date of actual payment"
    days = int(v["compliance_days"])
    b.numbered(f"I, therefore, through this notice call upon {you} to pay the said sum of {amount}{interest}, "
               f"within {days} days of the receipt of this notice, failing which my client shall be "
               f"constrained to initiate appropriate civil and/or criminal proceedings against {you} "
               f"before the competent court of law, entirely at your risk as to costs and consequences.")
    if v.get("notice_cost"):
        b.numbered(f"{you.capitalize()} {verb('is', 'are', n)} further liable to pay {rupees(v['notice_cost'])} "
                   "towards the cost of this notice.")
    b.para("A copy of this notice has been retained in my office for record and further necessary action.")
    b.space()
    b.right("Yours faithfully,")
    b.right(v["advocate_name"], bold=True)
    b.right(f"Advocate for {v['client_name']}")
    if v.get("advocate_enrolment"):
        b.right(f"Enrolment No. {v['advocate_enrolment']}")

    if days < 7:
        warnings.append("A compliance period of under 7 days may be treated as unreasonable; 15 days is customary.")
    if v["mode"] == "Email":
        warnings.append("Email service is valid, but keep proof of delivery; Registered Post A.D. is the safest "
                        "mode of service to rely on in later proceedings.")
    return Draft("legal_notice", "Legal Notice for Recovery of Money", b.blocks, warnings)


LEGAL_NOTICE = Template(
    id="legal_notice",
    name="Legal Notice - Recovery of Money",
    category="Notices",
    description="Pre-litigation demand notice calling upon the recipient to pay an outstanding amount.",
    fields=[
        *COMMON_ADVOCATE,
        FieldSpec("date", "Notice date", type="date", default="today", group="Notice"),
        FieldSpec("mode", "Mode of dispatch", type="select", group="Notice",
                  options=["Registered Post A.D.", "Speed Post", "Courier", "Email"],
                  default="Registered Post A.D."),
        FieldSpec("client_name", "Client (sender) name", group="Parties"),
        FieldSpec("client_details", "Client description / address", required=False, group="Parties",
                  placeholder="e.g. having its registered office at ..."),
        FieldSpec("recipients", "Recipients (noticees)", type="parties", group="Parties"),
        FieldSpec("facts", "Facts / transaction details", type="textarea", group="Facts",
                  help="One fact per line. They become numbered paragraphs in order."),
        FieldSpec("amount_due", "Amount due (Rs.)", type="amount", min=1, group="Claim"),
        FieldSpec("due_since", "Due since", type="date", required=False, group="Claim"),
        FieldSpec("interest_rate", "Interest rate (% p.a.)", type="number", required=False, min=0, max=36,
                  group="Claim"),
        FieldSpec("compliance_days", "Days to comply", type="number", default=15, min=1, max=90, group="Claim"),
        FieldSpec("notice_cost", "Cost of notice (Rs.)", type="amount", required=False, min=0, group="Claim"),
        FieldSpec("subject", "Subject line (optional)", required=False, group="Notice",
                  help="Leave blank to auto-generate from the amount."),
    ],
    build=build_legal_notice,
    sample={
        "advocate_name": "Adv. Priya Sharma", "advocate_enrolment": "D/1234/2015",
        "advocate_address": "Chamber No. 210, Saket Court Complex, New Delhi - 110017",
        "mode": "Registered Post A.D.",
        "client_name": "ABC Traders Pvt. Ltd.",
        "client_details": "a company incorporated under the Companies Act, 2013, having its registered office at 14, Industrial Area, Okhla Phase-II, New Delhi - 110020",
        "recipients": [{"name": "Mr. Ramesh Kumar", "details": "Proprietor, R.K. Enterprises, 22, Lajpat Nagar-II, New Delhi - 110024"}],
        "facts": "My client supplied goods to you under invoices dated 05.01.2025 and 20.02.2025 for a total value of Rs. 8,50,000/-.\nYou received the goods without any objection as to quality or quantity.\nYou paid only Rs. 1,00,000/- on 15.03.2025 and acknowledged the balance by your email dated 01.04.2025.",
        "amount_due": "750000", "due_since": "2025-04-01", "interest_rate": "18", "compliance_days": "15",
        "notice_cost": "11000",
    },
)


# =============================================== plaint: recovery of money

SUIT_TYPES = [
    "Civil Suit",
    "Commercial Suit (Commercial Courts Act, 2015)",
    "Summary Suit under Order XXXVII CPC",
]


def build_recovery_suit(v: dict) -> Draft:
    b = DocBuilder()
    warnings: list[str] = []
    P, D = v["plaintiffs"], v["defendants"]
    p_lbl, d_lbl = role("Plaintiff", len(P)), role("Defendant", len(D))
    suit = v["suit_type"]
    commercial = suit.startswith("Commercial")
    summary = suit.startswith("Summary")
    principal = Decimal(v["principal_amount"])
    pre_interest = Decimal(v.get("pre_suit_interest") or 0)
    total = principal + pre_interest

    b.title(f"In the Court of {v['court_name']}")
    short = "CS (COMM)" if commercial else "CS (OS)" if summary else "CS"
    b.center(f"{short} No. {BLANK} of {v['date'].year}", bold=True)
    b.space()
    b.left("IN THE MATTER OF:", bold=True)
    _party_block(b, P, "Plaintiff")
    b.center("VERSUS", bold=True)
    _party_block(b, D, "Defendant")
    b.space()
    heading = f"SUIT FOR RECOVERY OF {rupees(total).upper()}"
    if summary:
        heading += " UNDER ORDER XXXVII OF THE CODE OF CIVIL PROCEDURE, 1908"
    elif commercial:
        heading += " UNDER THE COMMERCIAL COURTS ACT, 2015 READ WITH ORDER VII RULE 1 CPC"
    else:
        heading += " UNDER ORDER VII RULE 1 OF THE CODE OF CIVIL PROCEDURE, 1908"
    heading += ", ALONG WITH PENDENTE LITE AND FUTURE INTEREST"
    b.center(heading, bold=True)
    b.left("MOST RESPECTFULLY SHOWETH:", bold=True)

    first = b.numbered(f"That the {p_lbl} {verb('is', 'are', len(P))} {_names(P)}. "
                       f"The present suit is being filed through {v['advocate_name']}, Advocate, "
                       f"duly authorised by the {p_lbl}.")
    b.numbered(f"That the {d_lbl} {verb('is', 'are', len(D))} {_names(D)}, against whom the present suit "
               "for recovery is being filed.")
    for fact in paragraphs(v["facts"]):
        b.numbered(that_clause(fact))

    if v.get("legal_notice_date"):
        b.numbered(f"That the {p_lbl} served a legal notice dated {short_date(v['legal_notice_date'])} upon the "
                   f"{d_lbl} calling upon {'him/her/it' if len(D) == 1 else 'them'} to pay the outstanding "
                   f"amount, but the {d_lbl} {verb('has', 'have', len(D))} failed to pay the same.")

    calc = f"a principal sum of {rupees(principal)}"
    if pre_interest:
        calc += f" along with interest of {rupees(pre_interest)} accrued up to the date of filing of the suit"
    b.numbered(f"That the {d_lbl} {verb('is', 'are', len(D))} liable to pay to the {p_lbl} {calc}, "
               f"aggregating to {rupees(total)}.")

    if commercial:
        if v.get("mediation") == "Urgent interim relief sought (exempt under Section 12A)":
            b.numbered("That the present suit contemplates urgent interim relief and is therefore exempt from "
                       "the requirement of pre-institution mediation under Section 12A of the Commercial "
                       "Courts Act, 2015.")
        else:
            b.numbered(f"That the {p_lbl} invoked pre-institution mediation under Section 12A of the Commercial "
                       "Courts Act, 2015; the mediation did not result in a settlement and the non-starter / "
                       "failure report is filed herewith.")
        b.numbered("That the dispute is a 'commercial dispute' within the meaning of Section 2(1)(c) of the "
                   "Commercial Courts Act, 2015 and the Specified Value of the suit is "
                   f"{rupees(total)}.")
    if summary:
        b.numbered("That the present suit is instituted under Order XXXVII of the Code of Civil Procedure, "
                   "1908 upon a written contract / liquidated demand, and no relief has been claimed in "
                   "this suit which does not fall within the ambit of Order XXXVII CPC.")

    coa_date, coa_place = v["cause_of_action_date"], v["cause_of_action_place"]
    b.numbered(f"That the cause of action for filing the present suit first arose on {short_date(coa_date)} "
               f"at {coa_place}, when the amount became due and payable, and it continues to subsist "
               f"as the {d_lbl} {verb('has', 'have', len(D))} failed to pay the same till date.")
    juris = v.get("jurisdiction_basis") or (
        f"the cause of action has arisen at {coa_place} and/or the {d_lbl} "
        f"{verb('resides or carries', 'reside or carry', len(D))} on business within the territorial "
        "jurisdiction of this Hon'ble Court")
    b.numbered(f"That this Hon'ble Court has territorial jurisdiction to try and entertain the present suit "
               f"as {juris}. The suit is within the pecuniary jurisdiction of this Hon'ble Court.")

    # Limitation: money suits are generally 3 years (Limitation Act, 1963).
    # We compute it rather than blindly asserting "within limitation".
    years = (v["date"] - coa_date).days / 365.25
    if years <= 3:
        b.numbered("That the present suit is within the period of limitation prescribed under the "
                   "Limitation Act, 1963.")
    else:
        b.numbered(f"That the present suit is within limitation as the period of limitation stands extended "
                   f"by {BLANK} [acknowledgment in writing under Section 18 / part payment under Section 19 "
                   "of the Limitation Act, 1963].")
        warnings.append(f"The cause of action ({short_date(coa_date)}) is {years:.1f} years before the filing "
                        "date. Money suits generally carry a 3-year limitation; plead and prove an "
                        "acknowledgment (S.18) or part-payment (S.19), or the suit may be dismissed as time-barred.")

    fee = f" and the requisite court fee of {rupees(v['court_fee'])} has been affixed" if v.get("court_fee") else \
        f" and the requisite court fee of Rs. {BLANK}/- has been affixed"
    b.numbered(f"That the suit is valued at {rupees(total)} for the purposes of court fees and jurisdiction{fee}.")
    if not v.get("court_fee"):
        warnings.append("Court fee not entered: compute it per the Court Fees Act, 1870 as applicable in your state.")

    b.numbered(f"That the {p_lbl} {verb('has', 'have', len(P))} not filed any other suit or proceeding on the "
               f"same cause of action against the {d_lbl} before this or any other court.")
    last = b.last_number

    b.center("PRAYER", bold=True)
    b.para(f"In view of the facts and circumstances stated above, it is most respectfully prayed that this "
           f"Hon'ble Court may be pleased to:")
    rate = _pct(v["interest_rate"]) if v.get("interest_rate") else f"{BLANK}% per annum"
    jointly = " jointly and severally" if len(D) > 1 else ""
    b.prayer_items([
        f"pass a decree for {rupees(total)} in favour of the {p_lbl} and against the {d_lbl}{jointly};",
        f"award pendente lite and future interest at the rate of {rate} on the principal amount from the "
        "date of filing of the suit till its realisation;",
        f"award the costs of the suit to the {p_lbl};",
        "pass such other and further order(s) as this Hon'ble Court may deem fit and proper in the facts "
        "and circumstances of the case.",
    ])
    _signature(b, v, p_lbl.upper())

    b.space()
    b.center("VERIFICATION", bold=True)
    b.para(f"Verified at {v.get('place') or BLANK} on this {long_date(v['date'])} that the contents of "
           f"paragraphs {first} to {last} of the plaint are true and correct to the knowledge of the "
           f"{p_lbl}, and those of the legal submissions are based on legal advice received and believed "
           "to be true. No part of it is false and nothing material has been concealed therefrom.")
    b.right(p_lbl.upper(), bold=True)
    if commercial:
        warnings.append("Commercial suits must be accompanied by a Statement of Truth (Order VI Rule 15A CPC as "
                        "amended by the Commercial Courts Act) in the prescribed format, in addition to the verification.")
    if summary:
        warnings.append("Order XXXVII suits must bear the inscription required by Order XXXVII Rule 2 below the "
                        "cause title and be based on a written instrument or liquidated demand.")
    return Draft("recovery_suit", f"Plaint - {suit}", b.blocks, warnings)


RECOVERY_SUIT = Template(
    id="recovery_suit",
    name="Plaint - Suit for Recovery of Money",
    category="Civil",
    description="Plaint for recovery of money as an ordinary civil suit, a commercial suit or an Order XXXVII summary suit.",
    fields=[
        FieldSpec("court_name", "Court", group="Court",
                  placeholder="e.g. District Judge (Commercial Court), South District, Saket, New Delhi"),
        FieldSpec("suit_type", "Type of suit", type="select", options=SUIT_TYPES, default=SUIT_TYPES[0], group="Court"),
        FieldSpec("mediation", "Pre-institution mediation (commercial only)", type="select", required=False,
                  options=["Mediation failed (non-starter report)",
                           "Urgent interim relief sought (exempt under Section 12A)"],
                  group="Court"),
        FieldSpec("plaintiffs", "Plaintiffs", type="parties", group="Parties"),
        FieldSpec("defendants", "Defendants", type="parties", group="Parties"),
        FieldSpec("facts", "Facts of the case", type="textarea", group="Facts",
                  help="One fact per line, in chronological order."),
        FieldSpec("legal_notice_date", "Legal notice date", type="date", required=False, group="Facts"),
        FieldSpec("principal_amount", "Principal amount (Rs.)", type="amount", min=1, group="Claim"),
        FieldSpec("pre_suit_interest", "Interest up to filing (Rs.)", type="amount", required=False, min=0, group="Claim"),
        FieldSpec("interest_rate", "Pendente lite / future interest (% p.a.)", type="number", required=False,
                  min=0, max=36, group="Claim"),
        FieldSpec("court_fee", "Court fee paid (Rs.)", type="amount", required=False, min=0, group="Claim"),
        FieldSpec("cause_of_action_date", "Cause of action arose on", type="date", group="Jurisdiction"),
        FieldSpec("cause_of_action_place", "Cause of action arose at", group="Jurisdiction", placeholder="e.g. Saket, New Delhi"),
        FieldSpec("jurisdiction_basis", "Basis of territorial jurisdiction (optional)", type="textarea",
                  required=False, group="Jurisdiction", help="Leave blank for the standard averment."),
        *COMMON_ADVOCATE,
        FieldSpec("place", "Place of filing", group="Filing", default="New Delhi"),
        FieldSpec("date", "Date of filing", type="date", default="today", group="Filing"),
    ],
    build=build_recovery_suit,
    sample={
        "court_name": "District Judge (Commercial Court), South District, Saket, New Delhi",
        "suit_type": SUIT_TYPES[1], "mediation": "Mediation failed (non-starter report)",
        "plaintiffs": [{"name": "ABC Traders Pvt. Ltd.", "details": "Through its Authorised Representative, 14, Industrial Area, Okhla Phase-II, New Delhi - 110020"}],
        "defendants": [{"name": "Mr. Ramesh Kumar", "details": "Proprietor, R.K. Enterprises, 22, Lajpat Nagar-II, New Delhi - 110024"}],
        "facts": "The Plaintiff is engaged in the wholesale supply of electrical goods.\nThe Defendant placed purchase orders and the Plaintiff supplied goods under invoices dated 05.01.2025 and 20.02.2025 worth Rs. 8,50,000/-.\nThe Defendant paid only Rs. 1,00,000/- on 15.03.2025 and acknowledged the balance by email dated 01.04.2025.",
        "legal_notice_date": "2025-06-10",
        "principal_amount": "750000", "pre_suit_interest": "135000", "interest_rate": "18", "court_fee": "9850",
        "cause_of_action_date": "2025-04-01", "cause_of_action_place": "New Delhi",
        "advocate_name": "Adv. Priya Sharma", "advocate_enrolment": "D/1234/2015",
        "advocate_address": "Chamber No. 210, Saket Court Complex, New Delhi - 110017",
        "place": "New Delhi",
    },
)


# ========================================================= bail application

BAIL_FORUMS = {
    "Sessions Court - Section 483 BNSS": "483",
    "Magistrate - Section 480 BNSS": "480",
}


def build_bail(v: dict) -> Draft:
    b = DocBuilder()
    warnings: list[str] = []
    section = BAIL_FORUMS[v["forum"]]
    applicant = v["applicant_name"]
    arrested: date = v["arrest_date"]
    days = (v["date"] - arrested).days
    if days < 0:
        warnings.append("Arrest date is after the application date; please check the dates.")
        days = 0

    b.title(f"In the Court of {v['court_name']}")
    b.center(f"Bail Application No. {BLANK} of {v['date'].year}", bold=True)
    b.space()
    b.left("IN THE MATTER OF:", bold=True)
    b.left(v["state_name"], bold=True)
    b.right("...PROSECUTION", bold=True)
    b.center("VERSUS", bold=True)
    b.left(applicant, bold=True)
    if v.get("applicant_details"):
        b.left(v["applicant_details"])
    b.right("...APPLICANT / ACCUSED", bold=True)
    b.space()
    b.center(f"FIR No. {v['fir_number']}  |  Police Station: {v['police_station']}  |  Under Sections: {v['sections']}",
             bold=True)
    b.space()
    b.center(f"APPLICATION UNDER SECTION {section} OF THE BHARATIYA NAGARIK SURAKSHA SANHITA, 2023 FOR GRANT "
             f"OF REGULAR BAIL ON BEHALF OF THE APPLICANT / ACCUSED", bold=True)
    b.left("MOST RESPECTFULLY SHOWETH:", bold=True)

    b.numbered(f"That the present FIR No. {v['fir_number']} was registered at Police Station "
               f"{v['police_station']} under Sections {v['sections']}, and the Applicant was arrested in "
               f"connection therewith on {short_date(arrested)}. The Applicant has been in custody since then, "
               f"i.e. for {days} day{'s' if days != 1 else ''} as on date.")
    cs = v["chargesheet"]
    if cs == "Filed":
        b.numbered("That the investigation is complete and the charge-sheet / police report has already been "
                   "filed. The Applicant is no longer required for the purposes of investigation and his/her "
                   "further incarceration would serve no useful purpose.")
    elif cs == "Not filed":
        b.numbered("That the charge-sheet has not been filed till date. Nothing remains to be recovered at the "
                   "instance of the Applicant, and the Applicant is no longer required for custodial interrogation.")
        if days > 60:
            warnings.append(f"The Applicant has been in custody {days} days without a charge-sheet. Check eligibility "
                            "for default bail under Section 187(3) BNSS (60 or 90 days depending on the "
                            "maximum punishment) - it is an indefeasible right if applied for before the charge-sheet is filed.")

    for g in paragraphs(v["grounds"]):
        b.numbered(that_clause(g))

    b.numbered("That the Applicant has deep roots in society, is not a flight risk, and there is no likelihood "
               "of the Applicant tampering with evidence or influencing witnesses.")
    prev = (v.get("previous_applications") or "").strip()
    b.numbered(f"That {prev}" if prev else
               "That no other bail application of the Applicant is pending before, or has been decided by, any "
               "other court in the present FIR.")
    surety = f" and is ready to furnish {v['surety']}" if v.get("surety") else \
        " and is ready to furnish personal bond and surety to the satisfaction of this Hon'ble Court"
    b.numbered(f"That the Applicant undertakes to abide by all terms and conditions that may be imposed by this "
               f"Hon'ble Court{surety}.")

    b.center("PRAYER", bold=True)
    b.para("It is, therefore, most respectfully prayed that this Hon'ble Court may be pleased to:")
    b.prayer_items([
        f"release the Applicant {applicant} on regular bail in FIR No. {v['fir_number']}, P.S. "
        f"{v['police_station']}, under Sections {v['sections']}, on such terms and conditions as this Hon'ble "
        "Court may deem fit;",
        "pass such other and further order(s) as this Hon'ble Court may deem fit and proper in the interest of justice.",
    ])
    _signature(b, v, "APPLICANT / ACCUSED")
    if section == "480":
        warnings.append("For offences punishable with death or imprisonment for life, a Magistrate's power to grant "
                        "bail under Section 480 BNSS is restricted; consider approaching the Sessions Court under Section 483.")
    return Draft("bail_application", "Regular Bail Application (BNSS, 2023)", b.blocks, warnings)


BAIL_APPLICATION = Template(
    id="bail_application",
    name="Regular Bail Application (BNSS)",
    category="Criminal",
    description="Application for regular bail under Section 480/483 of the Bharatiya Nagarik Suraksha Sanhita, 2023.",
    fields=[
        FieldSpec("court_name", "Court", group="Court", placeholder="e.g. Additional Sessions Judge-03, South, Saket, New Delhi"),
        FieldSpec("forum", "Forum / provision", type="select", options=list(BAIL_FORUMS),
                  default="Sessions Court - Section 483 BNSS", group="Court"),
        FieldSpec("state_name", "Prosecution", default="State (NCT of Delhi)", group="Parties"),
        FieldSpec("applicant_name", "Applicant / accused name", group="Parties"),
        FieldSpec("applicant_details", "Applicant details", required=False, group="Parties",
                  placeholder="S/o ..., aged about .. years, R/o ..."),
        FieldSpec("fir_number", "FIR number", group="Case", placeholder="e.g. 245/2026"),
        FieldSpec("police_station", "Police station", group="Case"),
        FieldSpec("sections", "Sections", group="Case", placeholder="e.g. 318(4), 61(2) BNS"),
        FieldSpec("arrest_date", "Date of arrest", type="date", group="Case"),
        FieldSpec("chargesheet", "Charge-sheet status", type="select", options=["Filed", "Not filed", "Unknown"],
                  default="Unknown", group="Case"),
        FieldSpec("grounds", "Grounds for bail", type="textarea", group="Grounds",
                  help="One ground per line."),
        FieldSpec("previous_applications", "Previous bail applications (optional)", type="textarea",
                  required=False, group="Grounds", help="Leave blank if none."),
        FieldSpec("surety", "Surety offered (optional)", required=False, group="Grounds",
                  placeholder="e.g. one surety of Rs. 50,000/- of a local resident"),
        *COMMON_ADVOCATE,
        FieldSpec("place", "Place", default="New Delhi", group="Filing"),
        FieldSpec("date", "Date", type="date", default="today", group="Filing"),
    ],
    build=build_bail,
    sample={
        "court_name": "Additional Sessions Judge-03, South District, Saket, New Delhi",
        "forum": "Sessions Court - Section 483 BNSS", "state_name": "State (NCT of Delhi)",
        "applicant_name": "Suresh Yadav", "applicant_details": "S/o Shri Mahesh Yadav, aged about 32 years, R/o H.No. 45, Sangam Vihar, New Delhi",
        "fir_number": "245/2026", "police_station": "Saket", "sections": "318(4), 61(2) BNS",
        "arrest_date": "2026-08-14", "chargesheet": "Not filed",
        "grounds": "The Applicant is innocent and has been falsely implicated in the present case.\nThe dispute is essentially civil and commercial in nature and has been given a criminal colour.\nThe Applicant is the sole earning member of his family, which includes aged parents and two minor children.\nThe Applicant has no previous criminal antecedents.",
        "advocate_name": "Adv. Priya Sharma", "advocate_enrolment": "D/1234/2015", "place": "New Delhi",
    },
)


# ================================================================ affidavit


def build_affidavit(v: dict) -> Draft:
    b = DocBuilder()
    warnings: list[str] = []
    if v.get("court_name"):
        b.title(f"In the Court of {v['court_name']}")
        if v.get("case_title"):
            b.center(v["case_title"], bold=True)
        b.space()
    b.title("Affidavit")
    who = v["deponent_name"]
    if v.get("relation"):
        who += f", {v['relation']}"
    age = f", aged about {int(v['age'])} years" if v.get("age") else ""
    b.para(f"I, {who}{age}, resident of {v['address']}, do hereby solemnly affirm and declare as under:")
    stmts = paragraphs(v["statements"])
    for s in stmts:
        b.numbered(that_clause(s))
    b.space()
    b.right("DEPONENT", bold=True)
    b.center("VERIFICATION", bold=True)
    b.para(f"Verified at {v['place']} on this {long_date(v['date'])} that the contents of paragraphs 1 to "
           f"{len(stmts)} of the above affidavit are true and correct to my knowledge and belief, no part of "
           "it is false and nothing material has been concealed therefrom.")
    b.right("DEPONENT", bold=True)
    warnings.append("The affidavit must be signed before an Oath Commissioner / Notary and stamped as per the "
                    "applicable Stamp Act.")
    return Draft("affidavit", "Affidavit", b.blocks, warnings)


AFFIDAVIT = Template(
    id="affidavit",
    name="General Affidavit",
    category="General",
    description="Affidavit with numbered declarations and verification, standalone or in support of a case.",
    fields=[
        FieldSpec("court_name", "Court (optional)", required=False, group="Court"),
        FieldSpec("case_title", "Case title (optional)", required=False, group="Court",
                  placeholder="e.g. ABC Traders Pvt. Ltd. vs Ramesh Kumar"),
        FieldSpec("deponent_name", "Deponent name", group="Deponent"),
        FieldSpec("relation", "Relation", required=False, group="Deponent", placeholder="e.g. S/o Shri Mahesh Yadav"),
        FieldSpec("age", "Age", type="number", required=False, min=18, max=120, group="Deponent"),
        FieldSpec("address", "Address", type="textarea", group="Deponent"),
        FieldSpec("statements", "Statements", type="textarea", group="Content",
                  help="One declaration per line; each becomes a numbered paragraph."),
        FieldSpec("place", "Place", default="New Delhi", group="Verification"),
        FieldSpec("date", "Date", type="date", default="today", group="Verification"),
    ],
    build=build_affidavit,
    sample={
        "deponent_name": "Ramesh Kumar", "relation": "S/o Late Shri Om Prakash", "age": "45",
        "address": "22, Lajpat Nagar-II, New Delhi - 110024",
        "statements": "I am the deponent herein and am fully conversant with the facts of the case.\nMy correct name is Ramesh Kumar, and I am also known as Ramesh Kumar Sharma.\nBoth names refer to one and the same person, i.e. myself.",
        "place": "New Delhi",
    },
)


TEMPLATES: dict[str, Template] = {t.id: t for t in (LEGAL_NOTICE, RECOVERY_SUIT, BAIL_APPLICATION, AFFIDAVIT)}
