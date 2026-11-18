"""Text to speech via the local Kokoro-FastAPI container (female voice).

Raw 24 kHz mono signed-16-bit PCM is streamed, so the first audio can leave before the
sentence is fully synthesised. Fixed scripts are pre-rendered at start-up and cached on
disk (permanent); dynamic lines are cached in a bounded LRU (memory) and a pruned disk folder.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from collections import OrderedDict
from collections.abc import AsyncIterator
from pathlib import Path

import httpx

from app.config import Settings

log = logging.getLogger("tts")
SAMPLE_RATE = 24000
MAX_DYNAMIC_MEM = 150  # entries kept in memory
MAX_DYNAMIC_DISK = 600  # files kept on disk
DYNAMIC_MAX_AGE_S = 3 * 86400

import numpy as np

# Kokoro pads every utterance with ~300-400 ms of silence. Pieces are trimmed and joined with short, deliberate pauses instead.
SILENCE_THRESHOLD = 250
LEAD_KEEP_MS, TRAIL_KEEP_MS = 15, 40
HOLD_BYTES = int(SAMPLE_RATE * 0.5) * 2  # tail held back while streaming, so trailing silence can be cut
PAUSE_SENTENCE_MS, PAUSE_CLAUSE_MS, PAUSE_LINE_MS = 190, 60, 230


_DIGIT_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]


def say_digits(number: str) -> str:
    """'1122' -> 'double one double two' (how emergency numbers are said aloud). Runs of 2 are 'double', of 3 'triple'."""
    out, i = [], 0
    while i < len(number):
        j = i
        while j < len(number) and number[j] == number[i]:
            j += 1
        run, word = j - i, _DIGIT_WORDS[int(number[i])]
        while run:
            if run >= 3:
                out.append(f"triple {word}")
                run -= 3
            elif run == 2:
                out.append(f"double {word}")
                run -= 2
            else:
                out.append(word)
                run -= 1
        i = j
    return " ".join(out)


def number_pattern(emergency_number: str = "1122") -> re.Pattern[str]:
    """Service numbers that must be read digit by digit (a TTS engine would say 'one thousand one hundred twenty-two')."""
    nums = {n for n in (emergency_number, "1122", "115", "911", "999") if n.isdigit()}
    return re.compile(r"(?<!\d)(?<!\d[.,])(" + "|".join(sorted(nums, key=len, reverse=True)) + r")(?!\d|[.,]\d|\s?(?:minutes?|mins?|hours?|days?|rupees|pkr|mg|ml))")


def spoken(text: str, pattern: re.Pattern[str] | None = None) -> str:
    """The words the voice engine should be given. Captions keep the written form ('1122')."""
    return (pattern or number_pattern()).sub(lambda m: say_digits(m.group(1)), text)


def silence(ms: int) -> bytes:
    return bytes(int(SAMPLE_RATE * ms / 1000) * 2)


def pause_ms(prev_piece: str) -> int:
    p = prev_piece.rstrip()
    if p.endswith((".", "!", "?", "।")):
        return PAUSE_SENTENCE_MS
    if p.endswith((",", ";", ":")):
        return PAUSE_CLAUSE_MS
    return 90


def _speech_bounds(x: np.ndarray) -> tuple[int, int] | None:
    idx = np.flatnonzero(np.abs(x.astype(np.int32)) > SILENCE_THRESHOLD)
    return (int(idx[0]), int(idx[-1])) if len(idx) else None


def trim_pcm(pcm: bytes) -> bytes:
    x = np.frombuffer(pcm, dtype=np.int16)
    b = _speech_bounds(x) if len(x) else None
    if b is None:
        return pcm
    a = max(0, b[0] - int(SAMPLE_RATE * LEAD_KEEP_MS / 1000))
    z = min(len(x), b[1] + int(SAMPLE_RATE * TRAIL_KEEP_MS / 1000))
    return x[a:z].tobytes()


_SENT = re.compile(r"(?<=[.!?।])\s+")
_CLAUSE = re.compile(r"(?<=[,;:])\s+")


def split_sentences(text: str, min_len: int = 24) -> list[str]:
    """Sentence split; the first sentence is further split at a comma so audio starts sooner."""
    parts = [p.strip() for p in _SENT.split(text.strip()) if p.strip()]
    out: list[str] = []
    for p in parts:
        if out and len(out[-1]) < min_len:
            out[-1] = f"{out[-1]} {p}"
        else:
            out.append(p)
    out = out or [text]
    if len(out[0]) > 70:  # long opening sentence: start speaking after the first clause
        clauses = [c for c in _CLAUSE.split(out[0], maxsplit=1) if c]
        if len(clauses) == 2 and len(clauses[0]) >= 18:
            out = [clauses[0], clauses[1], *out[1:]]
    return out


class TTS:
    def __init__(self, settings: Settings):
        self.s = settings
        self._numbers = number_pattern(settings.emergency_number)
        self.http = httpx.AsyncClient(base_url=settings.tts_url, timeout=httpx.Timeout(30.0, connect=3.0))
        self.fixed: dict[str, bytes] = {}
        self.dynamic: OrderedDict[str, bytes] = OrderedDict()
        self.dir = Path(settings.data_dir) / "tts-cache"
        self.dyn_dir = self.dir / "dyn"
        self.dyn_dir.mkdir(parents=True, exist_ok=True)
        self.ready = False
        self.warm_total = 0
        self.warm_done = 0
        self._fixed_keys: set[str] = set()
        # ONE synthesis at a time, strictly in request order: measured on the 2-4 core VPS, two parallel syntheses each run
        # 2-3x slower, so the sentence that is about to be needed arrives late and the voice stops mid-answer.
        self._sem = asyncio.Semaphore(1)
        self._inflight: dict[str, asyncio.Future] = {}  # single-flight: identical sentences share one synthesis
        self._prune_disk()

    def _key(self, text: str, voice: str | None = None) -> str:
        # lines containing a service number are cached under a new version: audio rendered before the digit-by-digit fix said "one thousand one hundred..."
        ver = "v3num" if self._numbers.search(text) else "v2trim"
        return hashlib.sha1(f"{ver}|{voice or self.s.tts_voice}|{self.s.tts_speed}|{text}".encode()).hexdigest()

    def _prune_disk(self) -> None:
        try:
            files = sorted(self.dyn_dir.glob("*.pcm"), key=lambda p: p.stat().st_mtime)
            now = time.time()
            for p in files[:]:
                if now - p.stat().st_mtime > DYNAMIC_MAX_AGE_S:
                    p.unlink(missing_ok=True)
                    files.remove(p)
            for p in files[: max(0, len(files) - MAX_DYNAMIC_DISK)]:
                p.unlink(missing_ok=True)
        except OSError:
            pass

    def cached(self, text: str, voice: str | None = None) -> bytes | None:
        k = self._key(text, voice)
        if k in self.fixed:
            return self.fixed[k]
        if k in self.dynamic:
            self.dynamic.move_to_end(k)
            return self.dynamic[k]
        for folder, store in ((self.dir, self.fixed), (self.dyn_dir, None)):
            f = folder / f"{k}.pcm"
            if f.exists():
                data = f.read_bytes()
                if store is not None:
                    store[k] = data
                else:
                    self._remember_dynamic(k, data)
                return data
        return None

    def _remember_dynamic(self, k: str, pcm: bytes) -> None:
        self.dynamic[k] = pcm
        self.dynamic.move_to_end(k)
        while len(self.dynamic) > MAX_DYNAMIC_MEM:
            self.dynamic.popitem(last=False)

    def _store(self, text: str, pcm: bytes, fixed: bool = False, voice: str | None = None) -> None:
        k = self._key(text, voice)
        try:
            if fixed:
                self.fixed[k] = pcm
                (self.dir / f"{k}.pcm").write_bytes(pcm)
            else:
                self._remember_dynamic(k, pcm)
                (self.dyn_dir / f"{k}.pcm").write_bytes(pcm)
        except OSError:
            pass

    async def healthy(self) -> bool:
        try:
            r = await self.http.get("/health", timeout=2.0)
            return r.status_code == 200
        except Exception:
            return False

    async def _stream_raw(self, text: str, voice: str | None = None) -> AsyncIterator[bytes]:
        payload = {
            "model": "kokoro", "input": spoken(text, self._numbers), "voice": voice or self.s.tts_voice,
            "response_format": "pcm", "speed": self.s.tts_speed, "stream": True,
        }
        carry = b""
        async with self._sem:
            async with self.http.stream("POST", "/v1/audio/speech", json=payload) as r:
                r.raise_for_status()
                async for chunk in r.aiter_bytes(4800):
                    data = carry + chunk
                    if len(data) % 2:
                        data, carry = data[:-1], data[-1:]
                    else:
                        carry = b""
                    if data:
                        yield data

    async def stream_shared(self, text: str, voice: str | None = None) -> AsyncIterator[bytes]:
        """Cached -> yield it. Already being synthesised for someone else -> wait for that result.
        Otherwise stream it (first audio leaves immediately) and publish the finished audio to waiters."""
        for _ in range(2):
            hit = self.cached(text, voice)
            if hit is not None:
                yield hit
                return
            k = self._key(text, voice)
            fut = self._inflight.get(k)
            if fut is None:
                break
            data = await asyncio.shield(fut)
            if data:
                yield data
                return
        k = self._key(text, voice)
        fut = asyncio.get_running_loop().create_future()
        self._inflight[k] = fut
        buf, done = bytearray(), False
        pend, started = bytearray(), False
        try:
            async for chunk in self._stream_raw(text, voice):
                pend += chunk
                if not started:  # drop leading silence as soon as speech begins
                    b = _speech_bounds(np.frombuffer(bytes(pend), dtype=np.int16))
                    if b is None:
                        continue
                    cut = max(0, b[0] - int(SAMPLE_RATE * LEAD_KEEP_MS / 1000)) * 2
                    del pend[:cut]
                    started = True
                if len(pend) > HOLD_BYTES:  # stream everything except a held-back tail (may be trailing silence)
                    out = bytes(pend[: len(pend) - HOLD_BYTES])
                    del pend[: len(pend) - HOLD_BYTES]
                    buf += out
                    yield out
            tail = trim_pcm(bytes(pend)) if started else bytes(pend)
            if tail:
                buf += tail
                yield tail
            done = True
        finally:
            if self._inflight.get(k) is fut:
                self._inflight.pop(k, None)
            data = bytes(buf) if done and buf else None
            if data:
                self._store(text, data, voice=voice)
            if not fut.done():
                fut.set_result(data)

    async def render(self, text: str, fixed: bool = False, voice: str | None = None) -> bytes:
        hit = self.cached(text, voice)
        if hit is not None:
            return hit
        buf = bytearray()
        async for chunk in self.stream_shared(text, voice):
            buf += chunk
        pcm = bytes(buf)
        if pcm and fixed:
            self._store(text, pcm, fixed=True, voice=voice)
        return pcm

    async def warm_voice(self, lines: dict[str, str], voice: str | None) -> None:
        """Pre-render lines in a specific voice (e.g. Hindi). Best effort, in the background."""
        for text in dict.fromkeys(lines.values()):
            if self.cached(text, voice) is not None:
                continue
            try:
                await self.render(text, fixed=True, voice=voice)
            except Exception:
                await asyncio.sleep(2)

    async def warm(self, lines: dict[str, str]) -> None:
        """Pre-render fixed scripts (retries until the TTS container is up)."""
        self.warm_total = len(lines)
        todo = dict(lines)
        delay = 2.0
        for _ in range(60):
            for key, text in list(todo.items()):
                try:
                    await self.render(text, fixed=True)
                    # make sure it is held as a permanent entry even if it came from the dynamic folder
                    k = self._key(text)
                    if k not in self.fixed:
                        data = self.cached(text)
                        if data:
                            self._store(text, data, fixed=True)
                    todo.pop(key)
                    self.warm_done = self.warm_total - len(todo)
                except Exception:
                    break
            if not todo:
                self.ready = True
                log.info("tts cache warm: %d fixed lines ready", self.warm_total)
                return
            await asyncio.sleep(delay)
            delay = min(delay * 1.3, 10.0)
        log.warning("tts cache warm-up gave up with %d lines pending", len(todo))
