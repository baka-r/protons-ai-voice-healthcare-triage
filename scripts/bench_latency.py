"""Latency benchmark against the live stack (serial, one caller). Reports time from "caller finished" to
the first byte of reply audio.

    docker compose exec -T agent python - < scripts/bench_latency.py
"""
import asyncio
import json
import statistics
import time

import httpx
import numpy as np
import websockets

WS = "ws://localhost:8000/ws/call"


async def open_call(ip):
    ws = await websockets.connect(WS, max_size=None, additional_headers={"X-Real-IP": ip})
    await ws.send(json.dumps({"type": "start"}))
    spoke = False
    while True:  # drain the greeting
        m = await asyncio.wait_for(ws.recv(), 60)
        if isinstance(m, bytes):
            continue
        j = json.loads(m)
        spoke |= j["type"] == "audio_start"
        if j["type"] == "state" and j["state"] == "listening" and spoke:
            return ws


async def turn(ws, payload):
    """payload: str (typed) or bytes (16 kHz PCM). Returns (ms to first audio byte, reply text, timing msg)."""
    t0 = time.perf_counter()
    await ws.send(json.dumps({"type": "text", "text": payload}) if isinstance(payload, str) else payload)
    first, text, timing, caller = None, "", None, ""
    while True:
        m = await asyncio.wait_for(ws.recv(), 60)
        if isinstance(m, bytes):
            if first is None:
                first = (time.perf_counter() - t0) * 1000
            continue
        j = json.loads(m)
        if j["type"] == "caption":
            if j["role"] == "assistant" and not text:
                text = j["text"]
            if j["role"] == "caller":
                caller = j["text"]
        elif j["type"] == "timing":
            timing = j
        elif j["type"] == "state" and j["state"] in ("listening", "handover") and first is not None:
            return first, text, timing, caller


async def speech(text, voice="am_adam"):
    async with httpx.AsyncClient(timeout=60) as h:
        r = await h.post("http://tts:8880/v1/audio/speech", json={"model": "kokoro", "input": text, "voice": voice, "response_format": "pcm", "speed": 1.0})
    x = np.frombuffer(r.content, dtype=np.int16).astype(np.float32)
    y = np.interp(np.linspace(0, len(x) - 1, int(len(x) * 16000 / 24000)), np.arange(len(x)), x)
    pad = np.zeros(int(0.2 * 16000), dtype=np.float32)
    return np.concatenate([pad, y, pad]).astype(np.int16).tobytes()


def row(name, ms, text, timing=None, extra=""):
    t = f" stt={timing.get('stt_ms')} nlu={timing.get('nlu_ms')}" if timing else ""
    print(f"  {name:<46}{ms:7.0f} ms  |{t} {extra} -> {text[:46]!r}")


async def main():
    results = {}
    ws = await open_call("10.7.0.1")
    print("TYPED turns (rules + parallel AI check)")
    cases = [
        ("info: OPD timings (cached after 1st)", "what are your OPD timings"),
        ("info again (audio cached)", "what are your OPD timings"),
        ("info: prayer room (needs LLM to understand)", "is there a prayer room"),
        ("persona: who are you (fixed script)", "who are you"),
        ("emergency by rules: chest pain", "I have chest pain"),
    ]
    for name, text in cases:
        if "emergency" in name:
            ws = await open_call("10.7.0.2")
        ms, reply, tm, _ = await turn(ws, text)
        row(name, ms, reply, tm)
        results[name] = ms
    ws2 = await open_call("10.7.0.3")
    ms, reply, tm, _ = await turn(ws2, "my husband is clutching his chest and sweating and has gone grey")
    row("emergency by AI only (no keyword hit)", ms, reply, tm)
    ws3 = await open_call("10.7.0.4")
    for name, text in [("booking: start", "I'd like to book an appointment"), ("booking: name+dob", "my name is Ayesha Khan and my date of birth is 12 March 1990"),
                       ("booking: department", "cardiology please"), ("booking: date", "tomorrow"), ("booking: time", "the first one"), ("booking: confirm", "yes")]:
        ms, reply, tm, _ = await turn(ws3, text)
        row(name, ms, reply, tm)

    print("\nVOICE turns (synthetic speech -> Groq Whisper -> engine -> Kokoro audio)")
    ws4 = await open_call("10.7.0.5")
    voice = []
    for text in ["What are your outpatient timings?", "Is there parking available?", "Who are you?", "I have chest pain.", ]:
        if text.startswith("I have chest"):
            ws4 = await open_call("10.7.0.6")
        pcm = await speech(text)
        dur = len(pcm) / 32000
        ms, reply, tm, heard = await turn(ws4, pcm)
        row(f"voice ({dur:.1f}s audio): {text}", ms, reply, tm, f"heard={heard!r}")
        voice.append(ms)
    print(f"\n  median voice-turn time-to-first-audio: {statistics.median(voice):.0f} ms  (excludes the ~380 ms end-of-speech wait done in the browser)")


asyncio.run(main())
