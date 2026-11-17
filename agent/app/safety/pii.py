"""PII masking for logs, stored utterances and anything sent to a cloud LLM."""
from __future__ import annotations

import re

_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[EMAIL]"),
    (re.compile(r"\b\d{5}-?\d{7}-?\d\b"), "[CNIC]"),
    (re.compile(r"\+?\d[\d\s\-]{8,}\d"), "[PHONE]"),
    (re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"), "[DATE]"),
    (re.compile(r"\b\d{6,}\b"), "[NUMBER]"),
]


def mask(text: str) -> str:
    out = text
    for rx, repl in _PATTERNS:
        out = rx.sub(repl, out)
    return out
