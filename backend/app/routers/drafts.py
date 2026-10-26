"""HTTP API for the legal draft generator."""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Response

from ..drafts.engine import ValidationError
from ..drafts.render import to_docx, to_text
from ..drafts.templates import TEMPLATES

router = APIRouter(prefix="/api/drafts", tags=["drafts"])


def _template(template_id: str):
    t = TEMPLATES.get(template_id)
    if not t:
        raise HTTPException(404, f"Unknown template '{template_id}'.")
    return t


def _generate(template_id: str, data: dict):
    try:
        return _template(template_id).generate(data)
    except ValidationError as e:
        # 422 with a per-field map so the form can highlight each bad input.
        raise HTTPException(422, {"code": "validation_error", "message": "Please fix the highlighted fields.",
                                  "fields": e.errors}) from None


@router.get("/templates")
def list_templates():
    """Templates with their full field schema -- the frontend builds its form
    from this, so the backend is the single source of truth."""
    return [t.summary() for t in TEMPLATES.values()]


@router.post("/{template_id}")
def generate(template_id: str, data: dict):
    draft = _generate(template_id, data)
    return {**draft.to_dict(), "text": to_text(draft)}


@router.post("/{template_id}/docx")
def generate_docx(template_id: str, data: dict):
    draft = _generate(template_id, data)
    name = re.sub(r"[^A-Za-z0-9]+", "-", draft.title).strip("-").lower() or "draft"
    return Response(
        to_docx(draft),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{name}.docx"'},
    )
