"""Protocol-level tests for EcourtsClient using a fake transport.

These pin down the behaviour we reverse-engineered from the portal's JS
(token rotation, error shapes) without hitting the live site.
"""
import json
from pathlib import Path

import pytest

from app.ecourts.client import EcourtsClient, normalise_cnr
from app.ecourts.errors import CaptchaError, CaseNotFound, InvalidInput, SessionExpired

FIX = Path(__file__).parent / "fixtures"


class FakeResp:
    def __init__(self, body, status=200, ctype="application/json"):
        self.text = body if isinstance(body, str) else json.dumps(body)
        self.status_code = status
        self.headers = {"content-type": ctype}
        self.content = self.text.encode()

    def json(self):
        return json.loads(self.text)


class FakeHttp:
    """Records each POST and replies from a queue."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.sent = []
        self.headers = {}

    def post(self, url, data=None, headers=None, timeout=None):
        self.sent.append((url, dict(data)))
        return FakeResp(self.replies.pop(0))


def make_client(replies, token="t0"):
    c = EcourtsClient(base_url="https://example.test/ecourtindia_v6/")
    c.http = FakeHttp(replies)
    c.token = token
    return c


def test_token_rotates_between_calls():
    c = make_client([
        {"status": 1, "dist_list": "<option value='8'>South</option>", "app_token": "t1"},
        {"status": 1, "complex_list": "<option value='1080010@1@Y'>Saket</option>", "app_token": "t2"},
    ])
    assert c.districts("26") == [{"value": "8", "label": "South"}]
    cx = c.complexes("26", "8")
    assert cx[0]["requires_establishment"] is True
    # Each request carried the token issued by the previous response.
    assert [d["app_token"] for _, d in c.http.sent] == ["t0", "t1"]
    assert all(d["ajax_req"] == "true" for _, d in c.http.sent)
    assert c.token == "t2"


def test_invalid_request_kills_session():
    c = make_client([{"errormsg": "<strong>Oops!</strong> Invalid Request", "app_token": ""}])
    with pytest.raises(SessionExpired):
        c.districts("26")


def test_wrong_captcha():
    c = make_client([{"status": 0, "div_captcha": "<span>Invalid Captcha</span>", "app_token": "t1"}])
    with pytest.raises(CaptchaError) as e:
        c.search_cnr("DLND020000602007", "abc123")
    assert "Invalid Captcha" in e.value.message
    assert c.http.sent[0][1]["cino"] == "DLND020000602007"


def test_cnr_success_uses_real_fragment():
    html = (FIX / "cnr_DLND020000602007_partial.html").read_text(encoding="utf-8")
    c = make_client([{"status": 1, "casetype_list": html, "app_token": "t1"}])
    case = c.search_cnr("dlnd-0200-0060-2007", "x")
    assert case["case_details"]["cnr_number"] == "DLND020000602007"


def test_cnr_not_found():
    c = make_client([{"status": 1, "casetype_list": "<span>This Case Code does not exists</span>", "app_token": "t"}])
    with pytest.raises(CaseNotFound):
        c.search_cnr("DLND020000602007", "x")


def test_cnr_validation():
    assert normalise_cnr(" dlnd02 0000602007 ") == "DLND020000602007"
    with pytest.raises(InvalidInput):
        normalise_cnr("12345")


def test_case_number_requires_establishment_when_flagged():
    c = make_client([])
    with pytest.raises(InvalidInput):
        c.search_case_number(state_code="26", dist_code="8", complex_value="1080010@1,2@Y", est_code="",
                             case_type="1", case_no="233", year="2024", captcha="x")
    assert c.http.sent == []  # failed fast, no captcha wasted
