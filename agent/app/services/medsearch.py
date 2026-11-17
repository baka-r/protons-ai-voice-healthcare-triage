"""Medical reference lookup: MedlinePlus (US National Library of Medicine) with a Wikipedia fallback.

Free, no API key, reputable. Only the symptom words are sent (never names, dates of birth or contact details).
Results are untrusted reference text for the model to summarise; the model never receives instructions from them.
"""
from __future__ import annotations

import html
import logging
import re
import xml.etree.ElementTree as ET
from collections import OrderedDict

import httpx

log = logging.getLogger("medsearch")

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_STOP = {
    "i", "im", "i'm", "am", "is", "are", "the", "a", "an", "my", "me", "to", "of", "and", "or", "it", "its", "its", "what", "do", "does", "should", "can",
    "how", "have", "has", "had", "been", "since", "for", "with", "like", "ahving", "having", "feeling", "feel", "please", "tell", "about", "why",
    "very", "really", "just", "some", "bit", "little", "in", "on", "at", "when", "that", "this", "not", "no", "yes", "get", "got", "so", "but",
}


def clean(text: str, limit: int = 700) -> str:
    t = html.unescape(_TAG.sub(" ", html.unescape(text)))
    return _WS.sub(" ", t).strip()[:limit]


def build_query(*texts: str, label: str | None = None) -> str:
    words: list[str] = []
    for t in texts:
        for w in re.findall(r"[a-zA-Z']+", t.lower()):
            if w not in _STOP and len(w) > 2 and w not in words:
                words.append(w)
    q = " ".join(words[:7])
    if label and label not in q:
        q = f"{label} {q}".strip()
    return f"{q} symptoms causes".strip()


class MedSearch:
    def __init__(self) -> None:
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(4.0, connect=2.0), headers={"User-Agent": "hania-demo/1.0"})
        self.cache: OrderedDict[str, list[dict]] = OrderedDict()
        self.last_error: str | None = None

    async def search(self, query: str, n: int = 3) -> list[dict]:
        q = query.strip()
        if not q:
            return []
        if q in self.cache:
            self.cache.move_to_end(q)
            return self.cache[q]
        results: list[dict] = []
        try:
            results = await self._medlineplus(q, n)
            if not results:
                results = await self._wikipedia(q, n)
            self.last_error = None
        except Exception as e:  # network down: the doctor mode still works from the model's own knowledge
            self.last_error = type(e).__name__
            log.info("medical search unavailable: %s", self.last_error)
        if results:
            self.cache[q] = results
            while len(self.cache) > 200:
                self.cache.popitem(last=False)
        return results

    async def _medlineplus(self, q: str, n: int) -> list[dict]:
        r = await self.http.get("https://wsearch.nlm.nih.gov/ws/query", params={"db": "healthTopics", "term": q, "retmax": n})
        r.raise_for_status()
        root = ET.fromstring(r.text)
        out = []
        for doc in root.iter("document"):
            fields: dict[str, str] = {}
            for c in doc.findall("content"):
                fields.setdefault(c.get("name", ""), c.text or "")
            title, summary = clean(fields.get("title", ""), 120), clean(fields.get("FullSummary", ""), 700)
            if title and summary:
                out.append({"source": "MedlinePlus", "title": title, "snippet": summary, "url": doc.get("url", "")})
        return out[:n]

    async def _wikipedia(self, q: str, n: int) -> list[dict]:
        r = await self.http.get("https://en.wikipedia.org/w/api.php", params={
            "action": "query", "format": "json", "generator": "search", "gsrsearch": q, "gsrlimit": n,
            "prop": "extracts", "exintro": 1, "explaintext": 1, "exchars": 600,
        })
        r.raise_for_status()
        pages = (r.json().get("query") or {}).get("pages", {})
        return [{"source": "Wikipedia", "title": p["title"], "snippet": clean(p.get("extract", ""), 600), "url": ""}
                for p in sorted(pages.values(), key=lambda p: p.get("index", 99)) if p.get("extract")][:n]
