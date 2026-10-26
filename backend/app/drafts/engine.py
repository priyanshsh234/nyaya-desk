"""Core of the draft generator: field schema, validation, document model.

Design
------
* **Schema-driven.** Each template declares its fields (`FieldSpec`). The
  same schema drives (a) the API's validation and (b) the frontend form,
  which is rendered dynamically from `GET /api/drafts/templates`. Adding a
  template therefore needs zero frontend changes.
* **Block-based output, not a string.** A template emits a list of typed
  blocks (title, centered line, numbered paragraph, signature...). Every
  output format -- on-screen preview, plain text, .docx -- is a pure function
  of that list, so they can never drift apart. Paragraph numbers are assigned
  here, once, for the same reason.
* **Warnings, not silent assumptions.** Templates can attach warnings
  (e.g. "this suit looks time-barred") that the UI shows next to the draft.
  The generator never invents facts; anything it cannot know is left as a
  visible blank ("________") for the lawyer to fill.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

BLANK = "________"


# ---------------------------------------------------------------- schema


@dataclass
class FieldSpec:
    name: str
    label: str
    # text | textarea | date | amount | number | select | parties
    type: str = "text"
    required: bool = True
    help: str = ""
    placeholder: str = ""
    options: list[str] | None = None
    default: Any = None
    group: str = "General"
    min: float | None = None
    max: float | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        if d["type"] == "date" and d["default"] == "today":
            d["default"] = date.today().isoformat()
        return d


class ValidationError(Exception):
    def __init__(self, errors: dict[str, str]):
        super().__init__("Invalid input")
        self.errors = errors


def _empty(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, list) and not v)


def validate(fields: list[FieldSpec], data: dict) -> dict:
    """Coerce raw JSON values to Python types and collect *all* errors at
    once (better UX than failing on the first bad field)."""
    out: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for f in fields:
        raw = data.get(f.name, None)
        if _empty(raw):
            if f.default is not None:
                raw = date.today().isoformat() if f.default == "today" else f.default
            elif f.required:
                errors[f.name] = f"{f.label} is required."
                continue
            else:
                out[f.name] = None
                continue
        try:
            out[f.name] = _coerce(f, raw)
        except ValueError as e:
            errors[f.name] = str(e)
    if errors:
        raise ValidationError(errors)
    return out


def _coerce(f: FieldSpec, raw: Any) -> Any:
    if f.type in ("text", "textarea"):
        s = str(raw).strip()
        if len(s) > 20000:
            raise ValueError(f"{f.label} is too long.")
        return s
    if f.type == "select":
        s = str(raw).strip()
        if f.options and s not in f.options:
            raise ValueError(f"{f.label} must be one of: {', '.join(f.options)}.")
        return s
    if f.type == "date":
        try:
            return date.fromisoformat(str(raw)[:10])
        except ValueError:
            raise ValueError(f"{f.label} must be a valid date (YYYY-MM-DD).") from None
    if f.type in ("amount", "number"):
        try:
            # Accept "12,50,000" as typed by Indian users.
            n = Decimal(str(raw).replace(",", "").strip())
        except InvalidOperation:
            raise ValueError(f"{f.label} must be a number.") from None
        if f.min is not None and n < Decimal(str(f.min)):
            raise ValueError(f"{f.label} must be at least {f.min:g}.")
        if f.max is not None and n > Decimal(str(f.max)):
            raise ValueError(f"{f.label} must be at most {f.max:g}.")
        return n if f.type == "amount" else (int(n) if n == int(n) else float(n))
    if f.type == "parties":
        if not isinstance(raw, list):
            raise ValueError(f"{f.label} must be a list.")
        parties = []
        for p in raw:
            name = str((p or {}).get("name", "")).strip()
            if name:
                parties.append({"name": name, "details": str(p.get("details", "")).strip()})
        if f.required and not parties:
            raise ValueError(f"At least one entry is required in {f.label}.")
        return parties
    raise ValueError(f"Unsupported field type {f.type}")


# ------------------------------------------------------------- document


@dataclass
class Block:
    # title | subtitle | center | para | numbered | right | left | spacer | signature | prayer
    kind: str
    text: str = ""
    number: str | None = None
    bold: bool = False


@dataclass
class Draft:
    template_id: str
    title: str
    blocks: list[Block] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "template_id": self.template_id,
            "title": self.title,
            "blocks": [asdict(b) for b in self.blocks],
            "warnings": self.warnings,
        }


class DocBuilder:
    """Tiny fluent builder that owns paragraph numbering, so templates read
    top-to-bottom like the document they produce."""

    def __init__(self) -> None:
        self.blocks: list[Block] = []
        self._n = 0
        self._sub = 0

    def add(self, kind: str, text: str = "", **kw) -> "DocBuilder":
        # User values like "ABC Pvt. Ltd." often land right before a
        # sentence-ending period; collapse ".." (but keep an ellipsis "...").
        text = re.sub(r"(?<!\.)\.\.(?!\.)", ".", text)
        self.blocks.append(Block(kind=kind, text=text, **kw))
        return self

    def title(self, t: str) -> "DocBuilder":
        return self.add("title", t.upper(), bold=True)

    def center(self, t: str, bold: bool = False) -> "DocBuilder":
        return self.add("center", t, bold=bold)

    def para(self, t: str, bold: bool = False) -> "DocBuilder":
        return self.add("para", t, bold=bold)

    def right(self, t: str, bold: bool = False) -> "DocBuilder":
        return self.add("right", t, bold=bold)

    def left(self, t: str, bold: bool = False) -> "DocBuilder":
        return self.add("left", t, bold=bold)

    def space(self) -> "DocBuilder":
        return self.add("spacer")

    def numbered(self, t: str) -> int:
        """Numbered body paragraph; returns its number so templates can
        cross-reference ("contents of paras 1 to 12")."""
        self._n += 1
        self.add("numbered", t, number=f"{self._n}.")
        return self._n

    def prayer_items(self, items: list[str]) -> None:
        # Prayers are lettered (a), (b), ... per drafting convention.
        for i, t in enumerate(items):
            self.add("prayer", t, number=f"({chr(ord('a') + i)})")

    @property
    def last_number(self) -> int:
        return self._n


@dataclass
class Template:
    id: str
    name: str
    category: str
    description: str
    fields: list[FieldSpec]
    build: Callable[[dict], Draft]
    sample: dict = field(default_factory=dict)

    def summary(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "fields": [f.to_dict() for f in self.fields],
            "sample": self.sample,
        }

    def generate(self, data: dict) -> Draft:
        return self.build(validate(self.fields, data))
