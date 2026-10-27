"""
Column-name semantics shared by the profiler, classifier and mapping engine.

Everything here is deterministic and local: normalisation, token expansion and
similarity. No network calls and no dataset-specific hardcoding beyond common
business abbreviations.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
# Only a *suffix* makes a column an identifier (order_id, invoice_no). A
# middle word such as "Number vmail messages" is a measurement, not an id.
_ID_PATTERN = re.compile(
    r"(?:^|_)(?:id|ids|no|num|number|key|code|uuid|guid)$"
)

ABBREVIATIONS = {
    "amt": "amount",
    "qty": "quantity",
    "cust": "customer",
    "txn": "transaction",
    "trans": "transaction",
    "num": "number",
    "no": "number",
    "pct": "percent",
    "avg": "average",
    "tot": "total",
    "rev": "revenue",
    "prof": "profit",
    "dept": "department",
    "desc": "description",
    "addr": "address",
    "tel": "telephone",
    "dob": "birthdate",
    "yr": "year",
    "mo": "month",
    "wk": "week",
    "mgr": "manager",
    "emp": "employee",
    "acct": "account",
    "subscr": "subscriber",
    "intl": "international",
    "vmail": "voicemail",
    "vm": "voicemail",
    "mins": "minutes",
    "min": "minutes",
    "eve": "evening",
    "srv": "service",
    "serv": "service",
    "chrg": "charge",
    "chg": "charge",
}

STOPWORDS = {"of", "the", "a", "an", "in", "on", "for", "by", "to", "and", "with", "per"}

DATE_HINTS = (
    "date", "day", "month", "year", "time", "timestamp", "period", "week",
    "quarter", "created", "updated", "joined", "signup", "dob",
)

MEASURE_HINTS = (
    "amount", "total", "sum", "value", "price", "cost", "revenue", "sales",
    "profit", "quantity", "qty", "count", "charge", "minutes", "calls",
    "score", "rate", "spend", "income", "salary", "balance", "discount",
    "units", "impressions", "clicks", "conversions", "tenure", "age",
)


def normalize(name: str) -> str:
    """Lowercase, collapse separators and camelCase into a single canonical form."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(name or ""))
    cleaned = _NON_ALNUM.sub("_", spaced.lower()).strip("_")
    return re.sub(r"_+", "_", cleaned)


def tokens(name: str) -> list[str]:
    """Normalised tokens with simple singularisation and abbreviation expansion."""
    result: list[str] = []
    for raw in normalize(name).split("_"):
        if not raw or raw in STOPWORDS:
            continue
        token = ABBREVIATIONS.get(raw, raw)
        if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            token = token[:-1]
        if token not in result:
            result.append(token)
    return result


def _expand(token_list: list[str]) -> list[str]:
    expanded: list[str] = []
    for token in token_list:
        expanded.append(token)
        expanded.append(ABBREVIATIONS.get(token, token))
    return expanded


def name_similarity(left: str, right: str) -> float:
    """0..1 similarity that combines token overlap and string similarity."""
    left_norm, right_norm = normalize(left), normalize(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0

    left_tokens, right_tokens = set(tokens(left)), set(tokens(right))
    overlap = 0.0
    if left_tokens and right_tokens:
        overlap = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
        if left_tokens <= right_tokens or right_tokens <= left_tokens:
            overlap = max(overlap, 0.85)

    # A short alias inside a longer name is strong evidence (sales_amount ↔ sales).
    contained = 0.0
    if len(right_norm) >= 4 and right_norm in left_norm:
        contained = 0.85
    elif len(left_norm) >= 4 and left_norm in right_norm:
        contained = 0.85

    # Character similarity is only trusted when the names are already close;
    # otherwise unrelated words share too many letters to be meaningful.
    sequence = SequenceMatcher(None, left_norm, right_norm).ratio()
    sequence_score = sequence * 0.8 if sequence >= 0.78 else 0.0

    return round(max(overlap, contained, sequence_score), 4)


def looks_like_id(name: str) -> bool:
    return bool(_ID_PATTERN.search(normalize(name))) or normalize(name) in {"id", "uuid", "guid"}


def looks_like_date(name: str) -> bool:
    normal = normalize(name)
    return any(hint in normal for hint in DATE_HINTS)


def looks_like_measure(name: str) -> bool:
    normal = normalize(name)
    return any(hint in normal for hint in MEASURE_HINTS)


def humanize(name: str) -> str:
    return re.sub(r"\s+", " ", normalize(name).replace("_", " ")).strip().title() or str(name)
