"""HTML -> structured data for the eCourts v6 portal.

The portal's AJAX endpoints return JSON, but the interesting payload inside
that JSON is a blob of server-rendered HTML (`casetype_list`, `case_data`,
`data_list`, `dist_list`, ...). This module turns those blobs into clean
Python dicts/lists.

Design choices
--------------
* **Class names first, headings second, generic fallback last.** The case
  history page tags most tables with descriptive CSS classes
  (`case_details_table`, `history_table`, `order_table`, ...). We use those
  when present. If a class is missing or renamed, we fall back to the nearest
  preceding heading text ("Case History", "Final Orders", ...). If neither
  matches, the table still ends up in `other_sections` rather than being
  silently dropped -- losing data is worse than returning it unlabelled.
* **No positional assumptions about rows.** Key/value tables on this portal
  sometimes put two pairs on one row (`Filing Number | x | Filing Date | y`)
  and sometimes one. We pair cells left-to-right, which handles both.
* **JS onclick handlers are data.** Order PDFs, hearing "business" details
  and case-list "View" buttons are not real links; they are `onclick` calls
  like `displayPdf(...)` / `viewHistory(...)`. We parse their arguments so the
  backend can replay the exact POST the browser would make.
* `html.parser` (stdlib) instead of lxml: the fragments are small, and it is
  more forgiving of the portal's unclosed tags.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl

from bs4 import BeautifulSoup, Tag

# --------------------------------------------------------------------------
# small text helpers
# --------------------------------------------------------------------------

_WS = re.compile(r"\s+")


def clean(text: str | None) -> str:
    """Collapse whitespace (incl. &nbsp;) and strip. Portal text is full of
    `&nbsp;` padding and stray newlines from the PHP templates."""
    if not text:
        return ""
    return _WS.sub(" ", text.replace("\xa0", " ")).strip()


def snake(label: str) -> str:
    """'Registration Date:' -> 'registration_date'. Stable keys make the JSON
    easy to consume regardless of the portal's punctuation/case quirks."""
    label = clean(label).rstrip(":").strip().lower()
    label = re.sub(r"[^a-z0-9]+", "_", label)
    return label.strip("_")


def cell_text(cell: Tag) -> str:
    return clean(cell.get_text(" "))


def soup_of(html: str) -> BeautifulSoup:
    return BeautifulSoup(html or "", "html.parser")


# --------------------------------------------------------------------------
# JS call argument parsing
# --------------------------------------------------------------------------

_JS_ARG = re.compile(r"""\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)"|([^,]*?))\s*(?:,|$)""")


def parse_js_call(onclick: str, fn_name: str) -> list[str] | None:
    """Extract the positional arguments of `fn_name(...)` from an onclick
    string. Handles single/double quoted and bare (numeric) args.

    >>> parse_js_call("viewHistory(123,'DLST01',3,'')", "viewHistory")
    ['123', 'DLST01', '3', '']
    """
    if not onclick:
        return None
    m = re.search(re.escape(fn_name) + r"\s*\((.*)\)", onclick, re.S)
    if not m:
        return None
    inner = m.group(1).strip()
    if not inner:
        return []
    args: list[str] = []
    pos = 0
    while pos < len(inner):
        am = _JS_ARG.match(inner, pos)
        if not am or am.end() == pos:
            break
        sq, dq, bare = am.groups()
        val = sq if sq is not None else dq if dq is not None else (bare or "")
        args.append(val.strip())
        pos = am.end()
    return args


# --------------------------------------------------------------------------
# dropdown <option> lists (districts, complexes, establishments, case types)
# --------------------------------------------------------------------------


def parse_options(html: str) -> list[dict]:
    """Turn `<option value='x'>Label</option>...` into [{value, label}].

    Placeholder options ("Select district", value '' or '0') are dropped so
    the frontend does not need to know about them.
    """
    out = []
    for opt in soup_of(html).find_all("option"):
        value = (opt.get("value") or "").strip()
        label = cell_text(opt)
        if value in ("", "0") or label.lower().startswith("select"):
            continue
        out.append({"value": value, "label": label})
    return out


def parse_select(html: str, select_id: str) -> list[dict]:
    """Options of a specific <select id=...> on a full page (used for the
    state list, which is rendered server-side into casestatus/index)."""
    sel = soup_of(html).find("select", id=select_id)
    return parse_options(str(sel)) if sel else []


def parse_complex_value(value: str) -> dict:
    """Court complex option values encode three things: `code@ests@flag`.

    e.g. '1060001@2,3,4@Y' -> complex 1060001, contains establishments
    2,3,4, and flag Y means "the user MUST pick an establishment" (the portal
    JS refuses to submit otherwise). We expose this so the UI can make the
    establishment dropdown required only when the portal requires it.
    """
    parts = (value or "").split("@")
    return {
        "complex_code": parts[0] if parts else "",
        "establishment_codes": [p for p in (parts[1].split(",") if len(parts) > 1 else []) if p],
        "requires_establishment": len(parts) > 2 and parts[2].upper() == "Y",
    }


# --------------------------------------------------------------------------
# case-number search result list
# --------------------------------------------------------------------------

VIEW_HISTORY_ARGS = [
    "case_no", "cino", "court_code", "hideparty", "search_flag",
    "state_code", "dist_code", "court_complex_code", "search_by",
]


def parse_case_list(html: str) -> list[dict]:
    """Parse `submitCaseNo`'s `case_data` table.

    Each result row has a "View" button: `viewHistory(case_no, cino, ...)`.
    We return those arguments as `view_args` so the API can call
    home/viewHistory for the selected case without another captcha (the
    portal only captchas the search, not the drill-down).

    Establishment group rows (a single wide cell naming the court) are
    remembered and attached to the following case rows.
    """
    soup = soup_of(html)
    results: list[dict] = []
    current_est = ""
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if not cells or tr.find("th"):
            continue  # header row
        link = tr.find(attrs={"onclick": re.compile(r"viewHistory", re.I)})
        if link is None:
            # A row with no View button is an establishment group header.
            txt = cell_text(tr)
            if txt:
                current_est = txt
            continue
        args = parse_js_call(link.get("onclick", ""), "viewHistory") or []
        view_args = dict(zip(VIEW_HISTORY_ARGS, args))
        texts = [cell_text(c) for c in cells]
        parties_cell = cells[2] if len(cells) > 2 else None
        parties = _split_vs(parties_cell) if parties_cell else {}
        results.append({
            "sr_no": texts[0] if texts else "",
            "case_number": texts[1] if len(texts) > 1 else "",
            "title": texts[2] if len(texts) > 2 else "",
            **parties,
            "establishment": current_est,
            "cnr": view_args.get("cino", ""),
            "view_args": view_args,
        })
    return results


def _split_vs(cell: Tag) -> dict:
    """'Punjab National Bank<br>Vs<br>Sunil Kumar' -> petitioner/respondent."""
    lines = [clean(x) for x in cell.get_text("\n").split("\n")]
    lines = [x for x in lines if x]
    for i, line in enumerate(lines):
        if line.lower().rstrip(".") in ("vs", "v/s", "versus", "v"):
            return {"petitioner": " ".join(lines[:i]), "respondent": " ".join(lines[i + 1:])}
    return {}


def parse_total_cases(html: str) -> int | None:
    m = re.search(r"Total number of cases\s*:\s*(\d+)", clean(soup_of(html).get_text(" ")), re.I)
    return int(m.group(1)) if m else None


# --------------------------------------------------------------------------
# full case history (CNR search result / viewHistory)
# --------------------------------------------------------------------------

# (substring of table CSS class, section key). Order matters: more specific
# patterns first ("final" orders before generic "order").
_CLASS_RULES = [
    ("case_details", "case_details"),
    ("case_status", "case_status"),
    ("petitioner", "petitioners"),
    ("respondent", "respondents"),
    ("acts", "acts"),
    ("fir", "fir_details"),
    ("lower_court", "subordinate_court"),
    ("subordinate", "subordinate_court"),
    ("history", "hearing_history"),
    ("transfer", "transfers"),
    ("ia", "ia_status"),
    ("order", "orders"),
]

# Same idea keyed on heading text, used when the class is missing/unknown.
_HEADING_RULES = [
    ("case details", "case_details"),
    ("case status", "case_status"),
    ("petitioner", "petitioners"),
    ("respondent", "respondents"),
    ("acts", "acts"),
    ("fir details", "fir_details"),
    ("subordinate", "subordinate_court"),
    ("lower court", "subordinate_court"),
    ("case history", "hearing_history"),
    ("history of case", "hearing_history"),
    ("transfer", "transfers"),
    ("ia status", "ia_status"),
    ("interlocutory", "ia_status"),
    ("judg", "orders"),
    ("order", "orders"),
]

_KV_SECTIONS = {"case_details", "case_status", "fir_details", "subordinate_court"}


def _classify(table: Tag, heading: str) -> str | None:
    # Only look at the portal's own semantic classes, which all use
    # underscores (case_details_table, acts_table, Petitioner_Advocate_table).
    # Bootstrap utilities use hyphens and would cause false hits: every table
    # has `table-bordered`/`border`, and "b-ORDER-ed" would otherwise classify
    # everything as an orders table.
    tokens = [c.lower() for c in (table.get("class") or []) if "_" in c]
    classes = " ".join(tokens)
    for needle, key in _CLASS_RULES:
        # Short needles must match a whole underscore-delimited word, so "ia"
        # doesn't hit "judicial" and "fir" doesn't hit "first_hearing".
        if len(needle) <= 3:
            if re.search(rf"(^|[\s_]){needle}([\s_]|$)", classes):
                return key
        elif needle in classes:
            return key
    h = heading.lower()
    for needle, key in _HEADING_RULES:
        if needle in h:
            return key
    return None


def _heading_for(table: Tag) -> str:
    """Nearest heading-like element before the table. The portal uses a mix
    of <h2>/<h3>/<h4> and bold <span>/<label> captions."""
    prev = table.find_previous(["h1", "h2", "h3", "h4", "h5", "h6"])
    return cell_text(prev) if prev else ""


def _kv_pairs(table: Tag) -> dict:
    """Pair cells left-to-right: [label, value, label, value, ...]."""
    out: dict[str, str] = {}
    for tr in table.find_all("tr"):
        cells = [cell_text(c) for c in tr.find_all(["td", "th"])]
        for i in range(0, len(cells) - 1, 2):
            key = snake(cells[i])
            if key:
                out[key] = cells[i + 1]
    return out


def _rows(table: Tag) -> tuple[list[str], list[list[Tag]]]:
    """Split a grid table into (header labels, body rows of cells)."""
    trs = table.find_all("tr")
    if not trs:
        return [], []
    header_tr = None
    for tr in trs:
        if tr.find("th"):
            header_tr = tr
            break
    if header_tr is None:
        header_tr = trs[0]
    headers = [snake(cell_text(c)) or f"col_{i}" for i, c in enumerate(header_tr.find_all(["th", "td"]))]
    body = [tr.find_all(["td", "th"]) for tr in trs if tr is not header_tr]
    return headers, [r for r in body if r]


def _grid(table: Tag) -> list[dict]:
    headers, body = _rows(table)
    out = []
    for cells in body:
        if len(cells) == 1 and len(headers) > 1:
            # A full-width row is a sub-heading/note (e.g. "Transferred
            # from court X"); keep it rather than mis-aligning columns.
            out.append({"note": cell_text(cells[0])})
            continue
        out.append({h: cell_text(c) for h, c in zip(headers, cells)})
    return out


_PARTY_START = re.compile(r"^\s*(\d+)\s*[\)\.]\s*")
_ADVOCATE = re.compile(r"^\s*advocate\s*[-:]*\s*", re.I)


def _parties(table: Tag) -> list[dict]:
    """Petitioner/Respondent cells look like:

        1) Punjab National Bank<br>&nbsp;&nbsp;Advocate- RAJESH KUMAR<br>
        2) Another Party<br>Address ...

    i.e. numbered entries, optional "Advocate-" line, optional address
    lines. A single unnumbered name is also common, so numbering is optional.
    """
    lines = [clean(x) for x in table.get_text("\n").split("\n")]
    lines = [x for x in lines if x]
    parties: list[dict] = []
    for line in lines:
        m = _PARTY_START.match(line)
        if m or not parties:
            parties.append({"name": _PARTY_START.sub("", line), "advocates": [], "details": []})
        elif _ADVOCATE.match(line):
            adv = _ADVOCATE.sub("", line)
            if adv:
                parties[-1]["advocates"].append(adv)
        else:
            parties[-1]["details"].append(line)
    for p in parties:
        p["advocate"] = ", ".join(p["advocates"])
        p["details"] = " ".join(p["details"])
    return parties


BUSINESS_ARGS = [
    "court_code", "dist_code", "nextdate1", "case_number1", "state_code",
    "disposal_flag", "businessDate", "court_no", "national_court_code",
    "search_by", "srno",
]

PDF_ARGS = ["normal_v", "case_val", "court_code", "filename", "appFlag"]


def _pdf_args(onclick: str) -> dict | None:
    """displayPdf() is called two ways across portal versions: with five
    positional args, or with a single pre-built query string. Accept both."""
    args = parse_js_call(onclick, "displayPdf")
    if args is None:
        return None
    if len(args) == 1 and "=" in args[0]:
        return dict(parse_qsl(args[0].lstrip("&"), keep_blank_values=True))
    return dict(zip(PDF_ARGS, args))


def _hearings(table: Tag) -> list[dict]:
    headers, body = _rows(table)
    out = []
    for cells in body:
        if len(cells) == 1 and len(headers) > 1:
            out.append({"note": cell_text(cells[0])})
            continue
        row = {h: cell_text(c) for h, c in zip(headers, cells)}
        link = None
        for c in cells:
            link = c.find(attrs={"onclick": re.compile("viewBusiness", re.I)})
            if link:
                break
        if link:
            args = parse_js_call(link.get("onclick", ""), "viewBusiness") or []
            row["business_args"] = dict(zip(BUSINESS_ARGS, args))
        out.append(row)
    return out


def _orders(table: Tag, heading: str) -> list[dict]:
    headers, body = _rows(table)
    kind = "final" if re.search(r"final|judg", heading, re.I) else "interim"
    out = []
    for cells in body:
        row = {h: cell_text(c) for h, c in zip(headers, cells)}
        link = None
        for c in cells:
            link = c.find(attrs={"onclick": re.compile("displayPdf", re.I)})
            if link:
                break
        row["type"] = kind
        if link:
            row["pdf_args"] = _pdf_args(link.get("onclick", ""))
        if any(v for k, v in row.items() if k not in ("type",)):
            out.append(row)
    return out


_NOT_FOUND = re.compile(
    r"(does not exist|not exists|record not found|no record|invalid cnr|this case code)", re.I
)


def looks_not_found(html: str) -> str | None:
    """Return the portal's own message if the fragment is a 'no such case'
    notice rather than a case page."""
    soup = soup_of(html)
    if soup.find("table"):
        return None
    txt = clean(soup.get_text(" "))
    return txt if _NOT_FOUND.search(txt) else None


def parse_case_detail(html: str) -> dict:
    """Parse a full case-history fragment into structured JSON.

    Output shape (all keys always present, empty when the portal has no data
    for that section -- predictable shape is friendlier to API consumers):
    """
    soup = soup_of(html)
    first_heading = soup.find(["h1", "h2", "h3"])
    result: dict = {
        "court_name": cell_text(first_heading) if first_heading else "",
        "case_details": {},
        "case_status": {},
        "petitioners": [],
        "respondents": [],
        "acts": [],
        "fir_details": {},
        "subordinate_court": {},
        "hearing_history": [],
        "orders": [],
        "ia_status": [],
        "transfers": [],
        "other_sections": [],
    }

    # Parties are NOT tables on the live portal: they are
    # <ul class="table table-bordered Petitioner_Advocate_table ..."><li>...
    # (confirmed from a real CNR response). So we also walk <ul>s, but only
    # ones whose class marks them as data (`*_table` / `*advocate*`), never
    # navigation lists.
    def _is_data_block(tag: Tag) -> bool:
        if tag.name == "table":
            return True
        cls = " ".join(tag.get("class") or []).lower()
        return "_table" in cls or "advocate" in cls

    for table in soup.find_all(["table", "ul"]):
        if not _is_data_block(table):
            continue
        # Nested blocks are handled as part of their parent.
        if table.find_parent(["table", "ul"]) is not None:
            continue
        heading = _heading_for(table)
        key = _classify(table, heading)
        if table.name == "ul" and key not in ("petitioners", "respondents"):
            # A list we don't specifically understand: keep its items.
            items = [cell_text(li) for li in table.find_all("li")]
            if items:
                result["other_sections"].append({"heading": heading, "rows": [{"item": i} for i in items]})
            continue
        if key in _KV_SECTIONS:
            result[key].update(_kv_pairs(table))
        elif key in ("petitioners", "respondents"):
            result[key].extend(_parties(table))
        elif key == "hearing_history":
            result[key].extend(_hearings(table))
        elif key == "orders":
            result[key].extend(_orders(table, heading))
        elif key in ("acts", "ia_status", "transfers"):
            result[key].extend(_grid(table))
        else:
            rows = _grid(table)
            if rows:
                result["other_sections"].append({"heading": heading, "rows": rows})

    _normalise_case_details(result)
    return result


def _normalise_case_details(result: dict) -> None:
    """Post-processing for well-known quirks."""
    cd = result["case_details"]
    # The portal appends a nag note to the CNR: "DLND02... (Note the CNR
    # number for future reference)". Keep just the identifier.
    for k in list(cd):
        if k.startswith("cnr"):
            m = re.search(r"[A-Z]{4}\d{12}", cd[k])
            if m:
                cd["cnr_number"] = m.group(0)
                if k != "cnr_number":
                    del cd[k]
    # Convenience summary fields so consumers don't need to dig.
    pet = ", ".join(p["name"] for p in result["petitioners"] if p.get("name"))
    res = ", ".join(p["name"] for p in result["respondents"] if p.get("name"))
    result["title"] = f"{pet} vs {res}" if pet and res else (pet or res)


# --------------------------------------------------------------------------
# misc fragments
# --------------------------------------------------------------------------


def parse_business(html: str) -> dict:
    """The 'business on date' popup is a small key/value table plus free
    text. Return both so nothing is lost."""
    soup = soup_of(html)
    kv = {}
    for table in soup.find_all("table"):
        kv.update(_kv_pairs(table))
    return {"fields": kv, "text": clean(soup.get_text(" "))}


def captcha_message(div_captcha_html: str | None) -> str:
    txt = clean(soup_of(div_captcha_html or "").get_text(" "))
    return txt or "Invalid captcha"
