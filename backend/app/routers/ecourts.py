"""HTTP API for the eCourts scraper.

Flow from the frontend's point of view:

    POST /sessions                      -> {session_id, states}
    GET  /sessions/{sid}/captcha        -> PNG (proxied from the portal)
    POST /sessions/{sid}/search/cnr     -> full case JSON
    -- or --
    GET  /sessions/{sid}/districts|complexes|establishments|case-types
    POST /sessions/{sid}/search/case-number -> list of matches
    GET  /sessions/{sid}/cases/{ref}    -> full case JSON for one match
    -- follow-ups from a case page --
    GET  /sessions/{sid}/orders/{ref}   -> order/judgment PDF
    GET  /sessions/{sid}/business/{ref} -> what happened on a hearing date

Endpoints are plain `def` (not `async def`) on purpose: `requests` is
blocking, and FastAPI runs sync endpoints in a threadpool, so a slow portal
call never blocks the event loop. Each call takes the session's lock because
the portal's rotating token forbids concurrent requests on one session.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field

from ..ecourts import store
from ..ecourts.client import EcourtsClient
from ..ecourts.errors import CaseNotFound

router = APIRouter(prefix="/api/ecourts", tags=["ecourts"])


class CnrSearch(BaseModel):
    cnr: str = Field(..., min_length=16, max_length=24, examples=["DLND020000602007"])
    captcha: str = Field(..., min_length=1, max_length=8)


class CaseNumberSearch(BaseModel):
    state_code: str = Field(..., examples=["26"])
    dist_code: str = Field(..., examples=["8"])
    complex_value: str = Field(..., description="Raw court-complex option value, e.g. '1080010@1,2@Y'")
    est_code: str = ""
    case_type: str
    case_no: str = Field(..., pattern=r"^\d{1,7}$")
    year: str = Field(..., pattern=r"^(19|20)\d{2}$")
    captcha: str = Field(..., min_length=1, max_length=8)


def _with_links(sid: str, case: dict) -> dict:
    """Turn opaque refs into absolute API paths the UI can link to directly."""
    for o in case.get("orders", []):
        o["pdf_url"] = f"/api/ecourts/sessions/{sid}/orders/{o['pdf_ref']}" if o.get("pdf_ref") else None
    for h in case.get("hearing_history", []):
        h["business_url"] = (f"/api/ecourts/sessions/{sid}/business/{h['business_ref']}"
                             if h.get("business_ref") else None)
    return case


def _envelope(case: dict, **source) -> dict:
    return {
        "source": {"portal": "eCourts District Courts (services.ecourts.gov.in)", **source},
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        # Order links are bound to the portal session that produced them.
        "links_expire_with_session": True,
        "case": case,
    }


def _ref(client: EcourtsClient, ref: str, kind: str) -> dict:
    payload = client.refs.get(ref)
    if not payload or payload.get("kind") != kind:
        raise CaseNotFound("Unknown or expired link. Run the search again.")
    return {k: v for k, v in payload.items() if k != "kind"}


@router.post("/sessions")
def create_session():
    sid, client = store.create()
    return {"session_id": sid, "states": client.states}


@router.get("/sessions/{sid}/captcha")
def captcha(sid: str):
    client = store.get(sid)
    with client.lock:
        png = client.captcha_png()
    # no-store: a cached captcha image would not match the session's code.
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.get("/sessions/{sid}/districts")
def districts(sid: str, state_code: str = Query(...)):
    client = store.get(sid)
    with client.lock:
        return client.districts(state_code)


@router.get("/sessions/{sid}/complexes")
def complexes(sid: str, state_code: str, dist_code: str):
    client = store.get(sid)
    with client.lock:
        return client.complexes(state_code, dist_code)


@router.get("/sessions/{sid}/establishments")
def establishments(sid: str, state_code: str, dist_code: str, complex_value: str):
    client = store.get(sid)
    with client.lock:
        return client.establishments(state_code, dist_code, complex_value)


@router.get("/sessions/{sid}/case-types")
def case_types(sid: str, state_code: str, dist_code: str, complex_value: str, est_code: str = ""):
    client = store.get(sid)
    with client.lock:
        return client.case_types(state_code, dist_code, complex_value, est_code)


@router.post("/sessions/{sid}/search/cnr")
def search_cnr(sid: str, body: CnrSearch):
    client = store.get(sid)
    with client.lock:
        case = client.search_cnr(body.cnr, body.captcha)
    return _envelope(_with_links(sid, case), search_type="cnr", cnr=case["case_details"].get("cnr_number"))


@router.post("/sessions/{sid}/search/case-number")
def search_case_number(sid: str, body: CaseNumberSearch):
    client = store.get(sid)
    with client.lock:
        result = client.search_case_number(**body.model_dump())
    for c in result["cases"]:
        c["details_url"] = f"/api/ecourts/sessions/{sid}/cases/{c['view_ref']}"
    return result


@router.get("/sessions/{sid}/cases/{ref}")
def case_details(sid: str, ref: str):
    client = store.get(sid)
    with client.lock:
        args = _ref(client, ref, "view")
        case = client.view_history(args)
    return _envelope(_with_links(sid, case), search_type="case_number", cnr=args.get("cino"))


@router.get("/sessions/{sid}/orders/{ref}")
def order_pdf(sid: str, ref: str):
    client = store.get(sid)
    with client.lock:
        pdf = client.order_pdf(_ref(client, ref, "pdf"))
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="order-{ref}.pdf"'})


@router.get("/sessions/{sid}/business/{ref}")
def business(sid: str, ref: str):
    client = store.get(sid)
    with client.lock:
        return client.business(_ref(client, ref, "business"))
