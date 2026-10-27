"""Programmatic replay of the eCourts v6 request flow.

How the portal works (reverse-engineered from DevTools + its own JS:
js/components.js `ajaxCall`, js/common_header.js, js/searchByCNR.js,
js/searchByCaseStatus.js):

1. GET  ?p=casestatus/index
     -> sets cookies SERVICES_SESSID (PHP session) + JSESSION (LB stickiness)
     -> renders <input id="app_token" value="<hex>">: the first token.
2. Every AJAX call is   POST ?p=<controller/action>
     body: <fields>&ajax_req=true&app_token=<current token>
   and every JSON response carries a NEW `app_token`. The token is single
   use / rotating: you must send the latest one on the next request. On
   error responses the token may instead appear after a `#####` delimiter
   or inside a non-JSON body, which `ajaxCall` also scrapes -- we mirror
   that logic in `_absorb_token`. Each AJAX call must also carry a custom
   header pair whose name and value rotate per session; they live in the
   session's own js/components.js (see `_discover_ajax_headers`).
3. Captcha: GET vendor/securimage/securimage_show.php?<random> returns a PNG
   whose answer is stored in the PHP session. So the image MUST be fetched
   with the same cookies as the subsequent search, which is why one
   `EcourtsClient` == one portal session == one user search flow.
4. CNR search:     POST cnr_status/searchByCNR/  cino, fcaptcha_code
   Case no search: fillDistrict -> fillcomplex -> fillCourtEstablishment ->
                   set_data -> fillCaseType -> submitCaseNo
   Drill-down:     POST home/viewHistory (no captcha) -> full case HTML
   Orders:         POST home/display_pdf -> {"order": "reports/x.pdf"}
                   then GET that path (same session) for the PDF bytes.

Captcha policy: this client never tries to solve captchas. The captcha
image is proxied to the end user, who types the answer. That respects the
portal's anti-automation control while still letting us automate everything
else in the flow; it is also more reliable than OCR, which fails often enough
to burn sessions.
"""
from __future__ import annotations

import logging
import os
import random
import re
import threading
import time
from pathlib import Path

import requests

from .. import config
from . import parser
from .errors import (
    CaptchaError, CaseNotFound, EcourtsError, InvalidInput, PortalUnavailable, SessionExpired,
)

log = logging.getLogger(__name__)

# The portal's jQuery `ajaxCall` adds a custom header pair to every AJAX call:
#     headers: { "delimeter": <value>, "<RandomName>": <value> }
# Both the second header's NAME and the shared VALUE rotate per session: each
# session is served its own `js/components.js?v=<n>` with fresh values, and the
# server rejects any AJAX call whose pair doesn't match ("Invalid Request").
# A hard-coded pair therefore can never work. We read the pair from the
# session's own components.js during bootstrap, exactly as the browser does
# by executing that script. (Confirmed by capturing a real browser request:
# the pair differed between two sessions minutes apart.)
_COMPONENTS_SRC = re.compile(r"""src=['"]([^'"]*js/components\.js[^'"]*)['"]""")
_DELIM_VALUE = re.compile(r"""var\s+delimeter\s*=\s*['"]([^'"]+)['"]""")
_HEADERS_BLOCK = re.compile(r"headers\s*:\s*\{([^}]*)\}", re.S)
_HEADER_USING_DELIM = re.compile(r"""['"]?([A-Za-z0-9_-]+)['"]?\s*:\s*delimeter\b""")
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
_TOKEN_INPUT = re.compile(r"""id=['"]app_token['"][^>]*value=['"]([0-9a-fA-F]*)['"]""")
_TOKEN_JSON = re.compile(r'"app_token"\s*:\s*"([0-9a-fA-F]*)"')
_CNR = re.compile(r"^[A-Z]{4}\d{12}$")


class EcourtsClient:
    """One portal session. Not thread-safe by itself; callers hold `lock`
    because the rotating app_token makes concurrent calls on one session
    impossible (two requests with the same token -> the second is rejected).
    """

    def __init__(self, base_url: str | None = None, timeout: float | None = None):
        self.base = (base_url or config.ECOURTS_BASE_URL).rstrip("/") + "/"
        # (connect, read): see config.py for why these differ.
        self.timeout = (config.ECOURTS_CONNECT_TIMEOUT, timeout or config.ECOURTS_TIMEOUT)
        self.http = requests.Session()
        self.http.headers.update({
            "User-Agent": _BROWSER_UA,
            "Accept-Language": "en-US,en;q=0.9",
        })
        self.token = ""
        # Per-session custom AJAX headers, discovered in bootstrap().
        self.ajax_headers: dict[str, str] = {}
        self.lock = threading.Lock()
        self.created_at = time.time()
        self.last_used = time.time()
        self.states: list[dict] = []
        # Opaque references handed to the frontend for follow-up calls
        # (order PDFs, business-on-date). Storing args server-side keeps the
        # public URLs short and stops callers from injecting arbitrary
        # parameters into requests we make with this session.
        self.refs: dict[str, dict] = {}
        # Remembered search context; viewBusiness needs dist/complex codes
        # that the browser would read from the page's dropdowns.
        self.context: dict = {}

    # ------------------------------------------------------------------ io

    def _url(self, path: str) -> str:
        return self.base + path.lstrip("/")

    @staticmethod
    def _network_error(e: requests.RequestException) -> PortalUnavailable:
        """Translate transport failures into something a user can act on.

        A failure to even *connect* is different from a slow portal: in
        practice it means eCourts is refusing this server's network. The
        portal is reachable from Indian connections but timed out from a
        US-hosted server, so we say that plainly instead of a bare
        exception name.
        """
        if isinstance(e, (requests.ConnectTimeout, requests.ConnectionError)):
            return PortalUnavailable(
                "eCourts did not accept a connection from this server.",
                hint="The portal appears to block networks outside India. Run the app locally "
                     "(see README) or host the backend in an Indian region.",
            )
        if isinstance(e, requests.Timeout):
            return PortalUnavailable("eCourts is responding too slowly right now.",
                                     hint="The portal is often overloaded; please try again in a minute.")
        return PortalUnavailable(f"Could not reach eCourts ({e.__class__.__name__}).")

    def _get(self, path: str, **kw) -> requests.Response:
        try:
            r = self.http.get(self._url(path), timeout=self.timeout, **kw)
        except requests.RequestException as e:
            raise self._network_error(e) from e
        if r.status_code >= 500:
            raise PortalUnavailable(f"eCourts returned HTTP {r.status_code}")
        self.last_used = time.time()
        return r

    def _absorb_token(self, text: str, data: dict | None) -> None:
        """Pick up the rotated token from any response shape (see module doc)."""
        if data is not None and "app_token" in data:
            self.token = data.get("app_token") or ""
            return
        if "#####" in text:
            tail = text.split("#####", 1)[1].strip()
            if tail:
                self.token = tail
                return
        m = _TOKEN_JSON.search(text)
        if m:
            self.token = m.group(1)

    def post(self, endpoint: str, fields: dict) -> dict:
        """POST to an AJAX endpoint the way `ajaxCall` does and return JSON.

        Raises a typed error for portal-level failures so callers never have
        to inspect `errormsg` themselves.
        """
        payload = {**fields, "ajax_req": "true", "app_token": self.token}
        origin = self.base.split("/ecourtindia")[0]
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Origin": origin,
            # The portal's referrer policy trims Referer to the bare origin.
            "Referer": origin + "/",
            **self.ajax_headers,
        }
        try:
            r = self.http.post(self._url("?p=" + endpoint), data=payload,
                               headers=headers, timeout=self.timeout)
        except requests.RequestException as e:
            raise self._network_error(e) from e
        self.last_used = time.time()
        if r.status_code >= 500:
            raise PortalUnavailable(f"eCourts returned HTTP {r.status_code}")

        # The portal sometimes prefixes JSON with a UTF-8 BOM or whitespace.
        text = r.text.lstrip("﻿").strip()
        try:
            data = r.json() if text.startswith("{") else None
        except ValueError:
            data = None
        self._absorb_token(text, data)
        self._dump(endpoint, text)

        if data is None:
            raise EcourtsError("eCourts returned an unexpected (non-JSON) response.")
        err = data.get("errormsg")
        if err:
            msg = parser.clean(parser.soup_of(err).get_text(" "))
            if not self.token:
                # "Invalid Request" with an empty token means the portal has
                # discarded our token chain; the session is unusable now.
                raise SessionExpired(msg or "eCourts rejected the request.",
                                     hint="Start a new search session and try again.")
            raise EcourtsError(msg)
        return data

    def _dump(self, endpoint: str, text: str) -> None:
        """Optionally persist raw responses for parser debugging."""
        if not config.DEBUG_DUMP_DIR:
            return
        try:
            d = Path(config.DEBUG_DUMP_DIR)
            d.mkdir(parents=True, exist_ok=True)
            name = re.sub(r"[^a-zA-Z0-9]+", "_", endpoint).strip("_")
            (d / f"{int(time.time() * 1000)}_{name}.json").write_text(text, encoding="utf-8")
        except OSError:
            log.warning("could not write debug dump", exc_info=True)

    # ------------------------------------------------------------ session

    def bootstrap(self) -> None:
        """Load casestatus/index: establishes cookies, first token, and gives
        us the state list for free (it is rendered into the page)."""
        r = self._get("?p=casestatus/index")
        m = _TOKEN_INPUT.search(r.text)
        if not m:
            raise PortalUnavailable("Could not initialise an eCourts session (no app_token on page).")
        self.token = m.group(1)
        self.states = parser.parse_select(r.text, "sess_state_code")
        self.ajax_headers = self._discover_ajax_headers(r.text)

    def _discover_ajax_headers(self, page_html: str) -> dict[str, str]:
        """Fetch this session's components.js and extract the custom header
        pair its `ajaxCall` sends (see the comment at the top of the module).
        Must use this session's cookies: the values are session-specific."""
        m = _COMPONENTS_SRC.search(page_html)
        if not m:
            raise PortalUnavailable("eCourts page layout changed: components.js not found.")
        src = m.group(1)
        # The page uses root-relative paths like /ecourtindia_v6/js/components.js?v=...
        url = (self.base.split("/ecourtindia")[0] + src) if src.startswith("/") else self._url(src)
        try:
            js = self.http.get(url, timeout=self.timeout).text
        except requests.RequestException as e:
            raise self._network_error(e) from e
        return parse_ajax_headers(js)

    def captcha_png(self) -> bytes:
        # Random query string defeats caching, exactly like the portal's
        # refresh button does. Each fetch invalidates the previous code.
        r = self._get(f"vendor/securimage/securimage_show.php?{random.random()}")
        ctype = r.headers.get("content-type", "")
        if not ctype.startswith("image/"):
            raise PortalUnavailable("eCourts did not return a captcha image.")
        return r.content

    def new_ref(self, payload: dict) -> str:
        ref = os.urandom(6).hex()
        self.refs[ref] = payload
        return ref

    # ---------------------------------------------------------- dropdowns

    def districts(self, state_code: str) -> list[dict]:
        data = self.post("casestatus/fillDistrict", {"state_code": state_code})
        return parser.parse_options(data.get("dist_list", ""))

    def complexes(self, state_code: str, dist_code: str) -> list[dict]:
        data = self.post("casestatus/fillcomplex", {"state_code": state_code, "dist_code": dist_code})
        out = parser.parse_options(data.get("complex_list", ""))
        for o in out:
            o.update(parser.parse_complex_value(o["value"]))
        return out

    def establishments(self, state_code: str, dist_code: str, complex_value: str) -> list[dict]:
        complex_code = parser.parse_complex_value(complex_value)["complex_code"]
        data = self.post("casestatus/fillCourtEstablishment", {
            "state_code": state_code, "dist_code": dist_code, "court_complex_code": complex_code,
        })
        return parser.parse_options(data.get("establishment_list", ""))

    def _set_data(self, state_code: str, dist_code: str, complex_value: str, est_code: str) -> None:
        """The browser calls set_data whenever complex/establishment changes;
        it stores the selection in the PHP session, and later endpoints
        (case types, search) can depend on it. Skipping it risks subtle
        'no records' results, so we always replay it."""
        self.post("casestatus/set_data", {
            "complex_code": complex_value,
            "selected_state_code": state_code,
            "selected_dist_code": dist_code,
            "selected_est_code": est_code or "",
        })

    def case_types(self, state_code: str, dist_code: str, complex_value: str, est_code: str = "") -> list[dict]:
        cx = parser.parse_complex_value(complex_value)
        self._set_data(state_code, dist_code, complex_value, est_code)
        data = self.post("casestatus/fillCaseType", {
            "state_code": state_code,
            "dist_code": dist_code,
            "court_complex_code": cx["complex_code"],
            # Same rule as the portal JS: est_code only when the complex
            # requires an explicit establishment.
            "est_code": est_code if cx["requires_establishment"] else "",
            "search_type": "c_no",
        })
        return parser.parse_options(data.get("casetype_list", ""))

    # ------------------------------------------------------------ searches

    def search_cnr(self, cnr: str, captcha: str) -> dict:
        cnr = normalise_cnr(cnr)
        data = self.post("cnr_status/searchByCNR/", {"cino": cnr, "fcaptcha_code": captcha.strip()})
        status = str(data.get("status", ""))
        if status == "0":
            raise CaptchaError(parser.captcha_message(data.get("div_captcha")),
                               hint="Fetch a new captcha and try again.")
        html = data.get("casetype_list") or ""
        nf = parser.looks_not_found(html)
        if nf or not html.strip():
            raise CaseNotFound(nf or f"No case found for CNR {cnr}.")
        self.context = {"search_by": "cnr"}
        return self._finish_case(html)

    def search_case_number(self, *, state_code: str, dist_code: str, complex_value: str,
                           est_code: str, case_type: str, case_no: str, year: str,
                           captcha: str) -> dict:
        cx = parser.parse_complex_value(complex_value)
        if cx["requires_establishment"] and not est_code:
            # Mirror the portal's own client-side validation so we fail
            # fast with a useful message instead of a vague portal error.
            raise InvalidInput("This court complex requires an establishment to be selected.")
        self._set_data(state_code, dist_code, complex_value, est_code)
        data = self.post("casestatus/submitCaseNo", {
            # Field names come from the #search_case form + the extra params
            # the portal JS appends (see searchByCaseStatus.js).
            "case_type": case_type,
            "search_case_no": case_no.strip(),
            "rgyear": year.strip(),
            "case_captcha_code": captcha.strip(),
            "state_code": state_code,
            "dist_code": dist_code,
            "court_complex_code": cx["complex_code"],
            "est_code": est_code or "",
            "case_no": case_no.strip(),
        })
        status = str(data.get("status", ""))
        if status == "0":
            raise CaptchaError(parser.captcha_message(data.get("div_captcha")),
                               hint="Fetch a new captcha and try again.")
        html = data.get("case_data") or ""
        cases = parser.parse_case_list(html)
        if not cases:
            raise CaseNotFound(parser.clean(parser.soup_of(html).get_text(" "))
                               or "No matching case found.")
        self.context = {
            "search_by": "CScaseNumber", "state_code": state_code,
            "dist_code": dist_code, "court_complex_code": cx["complex_code"],
        }
        for c in cases:
            c["view_ref"] = self.new_ref({"kind": "view", **c["view_args"]})
        return {"total": parser.parse_total_cases(html) or len(cases), "cases": cases}

    def view_history(self, view_args: dict) -> dict:
        """Drill-down from a result row. No captcha needed (by portal design)."""
        fields = {k: view_args.get(k, "") for k in parser.VIEW_HISTORY_ARGS}
        data = self.post("home/viewHistory", fields)
        html = data.get("data_list") or ""
        if not html.strip():
            raise CaseNotFound("eCourts returned no details for this case.")
        return self._finish_case(html)

    def _finish_case(self, html: str) -> dict:
        """Parse a case page and swap raw JS args for opaque refs that the
        API turns into fetchable links."""
        case = parser.parse_case_detail(html)
        for order in case["orders"]:
            args = order.pop("pdf_args", None)
            order["pdf_ref"] = self.new_ref({"kind": "pdf", **args}) if args else None
        for h in case["hearing_history"]:
            args = h.pop("business_args", None)
            h["business_ref"] = self.new_ref({"kind": "business", **args}) if args else None
        return case

    # ---------------------------------------------------------- follow-ups

    def order_pdf(self, args: dict) -> bytes:
        fields = {k: args.get(k, "") for k in parser.PDF_ARGS}
        data = self.post("home/display_pdf", fields)
        path = data.get("order")
        if not path:
            raise CaseNotFound("eCourts did not return a document for this order.")
        r = self._get(path)
        if not r.content.startswith(b"%PDF"):
            raise EcourtsError("The order document could not be downloaded from eCourts.")
        return r.content

    def business(self, args: dict) -> dict:
        ctx = self.context
        fields = {k: args.get(k, "") for k in parser.BUSINESS_ARGS}
        # The browser fills dist/complex from the visible dropdowns rather
        # than from the onclick args; replay that from our search context.
        if ctx.get("dist_code"):
            fields["dist_code"] = ctx["dist_code"]
        if ctx.get("search_by") != "cnr" and ctx.get("court_complex_code"):
            fields["court_complex_code"] = ctx["court_complex_code"]
        data = self.post("home/viewBusiness", fields)
        return parser.parse_business(data.get("data_list") or "")


def parse_ajax_headers(js: str) -> dict[str, str]:
    """From components.js source, return {"delimeter": v, "<Name>": v}.

    Only the `ajaxCall` function matters, so we start from its `var delimeter`
    assignment and take the first `headers: {...}` block after it; every key
    in that block whose value is the `delimeter` variable gets the value.
    """
    vm = _DELIM_VALUE.search(js)
    if not vm:
        raise PortalUnavailable("eCourts changed its request format (no AJAX header value found).")
    block = _HEADERS_BLOCK.search(js, vm.end())
    names = _HEADER_USING_DELIM.findall(block.group(1)) if block else []
    if not names:
        raise PortalUnavailable("eCourts changed its request format (no AJAX header names found).")
    return {name: vm.group(1) for name in names}


def normalise_cnr(cnr: str) -> str:
    """CNRs are 16 chars: 4-letter establishment code + 12 digits
    (e.g. DLND020000602007). Users paste them with spaces/dashes/lowercase."""
    c = re.sub(r"[^A-Za-z0-9]", "", cnr or "").upper()
    if not _CNR.match(c):
        raise InvalidInput("A CNR number is 16 characters: 4 letters followed by 12 digits "
                           "(e.g. DLND020000602007).")
    return c
