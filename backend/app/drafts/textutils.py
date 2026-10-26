"""Language helpers that make generated drafts read like a lawyer wrote them.

Indian pleadings have conventions a naive template gets wrong:
* money is grouped and spelled in the Indian system (lakh/crore), e.g.
  "Rs. 12,50,000/- (Rupees Twelve Lakh Fifty Thousand Only)";
* dates in verifications read "27th day of October, 2026";
* party labels must agree in number ("the Plaintiff" vs "the Plaintiffs",
  "has" vs "have").
All of this is deterministic string work, no external services.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
         "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen",
         "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two(n: int) -> str:
    if n < 20:
        return _ONES[n]
    return (_TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else "")).strip()


def _three(n: int) -> str:
    h, rest = divmod(n, 100)
    parts = []
    if h:
        parts.append(_ONES[h] + " Hundred")
    if rest:
        parts.append(_two(rest))
    return " ".join(parts)


def int_to_words_indian(n: int) -> str:
    """12500000 -> 'One Crore Twenty Five Lakh'. Crore repeats for very large
    numbers ("One Hundred Crore"), which is how Indian drafts express them."""
    if n == 0:
        return "Zero"
    if n < 0:
        return "Minus " + int_to_words_indian(-n)
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1000)
    parts = []
    if crore:
        parts.append(int_to_words_indian(crore) + " Crore")
    if lakh:
        parts.append(_two(lakh) + " Lakh")
    if thousand:
        parts.append(_two(thousand) + " Thousand")
    if n:
        parts.append(_three(n))
    return " ".join(parts)


def group_indian(n: int) -> str:
    """1250000 -> '12,50,000' (last three digits, then pairs)."""
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        pairs = []
        while len(head) > 2:
            pairs.insert(0, head[-2:])
            head = head[:-2]
        if head:
            pairs.insert(0, head)
        s = ",".join(pairs) + "," + tail
    return ("-" if n < 0 else "") + s


def rupees(amount: float | int | str | Decimal) -> str:
    """'Rs. 12,50,000.50/- (Rupees Twelve Lakh Fifty Thousand and Paise Fifty Only)'."""
    d = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    whole = int(d)
    paise = int((d - whole) * 100)
    figure = group_indian(whole) + (f".{paise:02d}" if paise else "")
    words = "Rupees " + int_to_words_indian(whole)
    if paise:
        words += f" and Paise {int_to_words_indian(paise)}"
    return f"Rs. {figure}/- ({words} Only)"


def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def long_date(d: date) -> str:
    """date(2026,10,27) -> '27th day of October, 2026' (verification style)."""
    return f"{ordinal(d.day)} day of {d.strftime('%B')}, {d.year}"


def short_date(d: date) -> str:
    """date(2026,10,27) -> '27.10.2026' (the usual in-body format)."""
    return d.strftime("%d.%m.%Y")


def join_names(names: list[str]) -> str:
    """['A'] -> 'A'; ['A','B'] -> 'A and B'; ['A','B','C'] -> 'A, B and C'."""
    names = [n for n in names if n]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def role(label: str, count: int) -> str:
    """Pluralise a party label: role('Plaintiff', 2) -> 'Plaintiffs'."""
    return label if count == 1 else label + "s"


def verb(singular: str, plural: str, count: int) -> str:
    return singular if count == 1 else plural


def paragraphs(text: str) -> list[str]:
    """Split free text into paragraphs. Users type facts either as one
    paragraph per line or separated by blank lines; accept both, and strip
    any numbering they typed themselves since we number paragraphs ourselves
    (double numbering like '1. 1. The plaintiff...' is a common template bug).
    """
    out = []
    for line in (text or "").replace("\r\n", "\n").split("\n"):
        line = re.sub(r"^\s*(\(?\d+[\.\)]|\(?[a-z][\.\)]|[-*•])\s+", "", line).strip()
        if line:
            out.append(line)
    return out


# Words that may be lower-cased when a sentence is turned into a "That ..."
# clause. Anything else (proper nouns, acronyms, "I") keeps its case, so
# "ABC Traders supplied..." never becomes "That aBC Traders supplied...".
_LOWERABLE = {
    "the", "my", "you", "your", "he", "she", "it", "his", "her", "they", "their", "we", "our",
    "on", "in", "after", "before", "despite", "thereafter", "accordingly", "since", "as", "when",
    "although", "however", "subsequently", "further", "both", "this", "these", "there", "a", "an",
    "both", "no", "all", "said",
}


def that_clause(sentence: str) -> str:
    """'The defendant failed to pay.' -> 'That the defendant failed to pay.'"""
    s = sentence.strip()
    if s.lower().startswith("that "):
        return "T" + s[1:]
    first = s.split(" ", 1)[0]
    if first.lower() in _LOWERABLE:
        s = s[0].lower() + s[1:]
    return "That " + s
