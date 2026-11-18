"""Measure audible gaps (buffer underruns) in streamed speech, the way the browser player would hear them.

    docker compose exec -T agent python - < scripts/bench_gaps.py
(optionally BASE_WS / ORIGIN env vars to run against a remote deployment)

The browser schedules every chunk at max(now + 30 ms, end of previous chunk). A chunk that arrives after the previous one
has finished playing therefore leaves an audible hole. We replay the arrival times through that same model.
"""
import asyncio
import json
import os
import random
import time

import websockets

WS = os.environ.get("BASE_WS", "ws://localhost:8000")
ORIGIN = os.environ.get("ORIGIN")
SR = 24000
LEAD = 0.03
PRE = float(os.environ.get("PREBUFFER", "0"))  # seconds of jitter buffer to emulate on the first chunk
SALT = str(random.randint(100, 999))

PROMPTS = [
    f"I have had a headache for {SALT} minutes and feel tired",
    f"my stomach hurts since {SALT} this morning and I feel like vomiting",
    f"I have a cough and runny nose for {SALT} days",
    "what are your OPD timings and which doctor sees cardiology patients",
    "tell me about your lab and radiology services",
    "I feel dizzy when I stand up, what could it be",
    "how do I get admitted and what is the discharge process",
    "do you accept insurance and how do payments work",
]


async def one(prompt, ip):
    h = {"X-Real-IP": ip}
    if ORIGIN:
        h["Origin"] = ORIGIN
    ws = await websockets.connect(f"{WS}/ws/call", max_size=None, additional_headers=h)
    try:
        await ws.send(json.dumps({"type": "start", "lang": "en"}))
        # wait for the greeting to finish
        t_end = time.time() + 60
        spoke = False
        while time.time() < t_end:
            m = await asyncio.wait_for(ws.recv(), 60)
            if isinstance(m, str):
                j = json.loads(m)
                if j["type"] == "audio_start":
                    spoke = True
                if j["type"] == "audio_end" and spoke:
                    break
        await ws.send(json.dumps({"type": "text", "text": prompt}))
        t0 = time.perf_counter()
        events = []  # (arrival, seconds_of_audio)
        caps = []
        first = None
        deadline = time.time() + 60
        spoke = False
        while time.time() < deadline:
            try:
                m = await asyncio.wait_for(ws.recv(), 8)
            except asyncio.TimeoutError:
                break
            now = time.perf_counter()
            if isinstance(m, bytes):
                events.append((now, len(m) / 2 / SR))
                if first is None:
                    first = now - t0
                continue
            j = json.loads(m)
            if j["type"] == "audio_start":
                spoke = True
            if j["type"] == "caption" and j["role"] == "assistant":
                caps.append(j["text"])
            if j["type"] == "audio_end" and events:  # (a late audio_end of the greeting arrives before any bytes)
                break
        return first, events, caps
    finally:
        await ws.close()


def analyse(events):
    if not events:
        return 0, 0, [], 0
    play_end = None
    base = events[0][0]
    gaps = []
    total = 0.0
    for arr, dur in events:
        want = arr + LEAD
        if play_end is None:
            start = want + PRE
        elif want > play_end:
            gaps.append((arr - base, want - play_end))
            start = want
        else:
            start = play_end
        play_end = start + dur
        total += dur
    return total, (events[-1][0] - base), gaps, len(events)


async def main():
    allgaps = []
    for i, p in enumerate(PROMPTS):
        try:
            first, ev, caps = await one(p, f"10.88.{random.randint(1, 250)}.{i + 1}")
        except Exception as e:
            print(f"ERR   {p[:48]!r}: {type(e).__name__} {e}")
            continue
        total, span, gaps, n = analyse(ev)
        # tiny gaps (< 40 ms) are inaudible; deliberate pauses are sent as audio, so any gap here is a true underrun
        real = [g for g in gaps if g[1] > 0.04]
        allgaps += [g[1] for g in real]
        worst = max((g[1] for g in real), default=0)
        print(f"first={first or 0:5.2f}s audio={total:5.1f}s arrived_in={span:5.1f}s chunks={n:3d} underruns={len(real)} worst={worst * 1000:5.0f}ms  {p[:44]!r}")
        print("        said:", " | ".join(caps)[:200])
        for at, g in real[:5]:
            print(f"        gap {g * 1000:5.0f} ms at +{at:4.1f}s of the stream")
        await asyncio.sleep(1)
    print()
    print(f"TOTAL underruns: {len(allgaps)}  worst: {max(allgaps, default=0) * 1000:.0f} ms  sum: {sum(allgaps):.2f} s")


asyncio.run(main())
