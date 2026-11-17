"""Text normalisation shared by the safety rules and the NLU rules."""
from __future__ import annotations

import re
import unicodedata

_URDU_MAP = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ة": "ہ", "ۃ": "ہ", "ە": "ہ"})
_TASHKEEL = re.compile(r"[ً-ٰٟـ]")
_INVISIBLE = re.compile(r"[​-‏‪-‮﻿]")


def normalize(text: str) -> str:
    """Lowercase, unify Urdu letter variants, strip diacritics/punctuation."""
    t = unicodedata.normalize("NFKC", text or "").lower()
    t = t.translate(_URDU_MAP)
    t = _TASHKEEL.sub("", t)
    t = _INVISIBLE.sub("", t)
    t = t.replace("’", "'").replace("‘", "'")
    t = re.sub(r"(.)\1{2,}", r"\1\1", t)  # saaaans -> saans
    t = re.sub(r"[^\w\s']", " ", t)
    t = t.replace("_", " ")
    return re.sub(r"\s+", " ", t).strip()


def tokens(norm: str) -> list[str]:
    return norm.split()
