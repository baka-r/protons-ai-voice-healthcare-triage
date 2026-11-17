"""Text normalisation shared by the safety rules and the NLU rules (English, Urdu script, Devanagari/Hindi)."""
from __future__ import annotations

import re
import unicodedata

_URDU_MAP = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ة": "ہ", "ۃ": "ہ", "ە": "ہ"})
_TASHKEEL = re.compile(r"[ً-ٰٟـ]")
_INVISIBLE = re.compile(r"[​-‏‪-‮﻿]")
_NUKTA = "़"  # Devanagari nukta: क़ ख़ ग़ ज़ फ़ are written with or without it by different engines


def _strip_punct(t: str) -> str:
    """Replace punctuation/symbols/controls with spaces but KEEP combining marks (Devanagari vowel signs are \\w-negative in Python's re)."""
    out = []
    for ch in t:
        cat = unicodedata.category(ch)
        if ch == "'" or cat[0] in "LMN":
            out.append(ch)
        else:
            out.append(" ")
    return "".join(out)


def normalize(text: str) -> str:
    """Lowercase, unify Urdu letter variants, strip diacritics/punctuation, keep Hindi vowel signs."""
    t = unicodedata.normalize("NFKC", text or "").lower()
    t = t.translate(_URDU_MAP)
    t = _TASHKEEL.sub("", t)
    t = _INVISIBLE.sub("", t)
    t = t.replace(_NUKTA, "")
    t = t.replace("’", "'").replace("‘", "'")
    t = re.sub(r"(.)\1{2,}", r"\1\1", t)  # saaaans -> saans
    t = _strip_punct(t)
    return re.sub(r"\s+", " ", t).strip()


def tokens(norm: str) -> list[str]:
    return norm.split()
