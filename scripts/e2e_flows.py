"""Live end-to-end flows: hospital flows, deep hospital knowledge, handover cancel, Hindi/Urdu, interruption.

    docker compose exec -T agent python - < scripts/e2e_flows.py
(optionally BASE_WS / BASE_HTTP / ORIGIN / PIN env vars to run against a remote deployment)
"""
import asyncio
import json
import os
import time

import httpx
import websockets

WS = os.environ.get("BASE_WS", "ws://localhost:8000")
HTTP = os.environ.get("BASE_HTTP", "http://localhost:8000")
ORIGIN = os.environ.get("ORIGIN")
PIN = os.environ.get("PIN", "1234")
results = []
_ip = [0]
DEVA = lambda s: any("ऀ" <= ch <= "ॿ" for ch in s)  # noqa: E731


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


class Call:
    def __init__(self):
        _ip[0] += 1
        self.ip = f"10.77.{(int(time.time()) // 7) % 200}.{_ip[0]}"

    async def open(self, lang="en"):
        h = {"X-Real-IP": self.ip}
        if ORIGIN:
            h["Origin"] = ORIGIN
        self.ws = await websockets.connect(f"{WS}/ws/call", max_size=None, additional_headers=h)
        self.caps, self.msgs, self.bytes = [], [], 0
        await self.ws.send(json.dumps({"type": "start", "lang": lang}))
        await self.wait_idle()
        return self

    async def wait_idle(self, timeout=90):
        end, spoke = time.time() + timeout, False
        while time.time() < end:
            try:
                m = await asyncio.wait_for(self.ws.recv(), timeout=max(0.1, end - time.time()))
            except (asyncio.TimeoutError, websockets.ConnectionClosed):
                return None
            if isinstance(m, bytes):
                self.bytes += len(m)
                continue
            j = json.loads(m)
            self.msgs.append(j)
            if j["type"] == "caption":
                self.caps.append((j["role"], j["text"]))
            elif j["type"] == "audio_start":
                spoke = True
            elif j["type"] == "state" and j["state"] in ("listening", "handover", "ended", "connected") and spoke:
                return j
        return None

    async def say(self, text, timeout=90):
        n = len(self.caps)
        t0 = time.perf_counter()
        await self.ws.send(json.dumps({"type": "text", "text": text}))
        st = await self.wait_idle(timeout)
        return " ".join(c[1] for c in self.caps[n:] if c[0] == "assistant"), st, time.perf_counter() - t0

    def last(self, typ):
        return next((m for m in reversed(self.msgs) if m["type"] == typ), None)

    async def close(self):
        try:
            await self.ws.send(json.dumps({"type": "end"}))
            await self.ws.close()
        except Exception:
            pass


async def main():
    async with httpx.AsyncClient(timeout=30) as h:
        tok = (await h.post(f"{HTTP}/api/staff/login", json={"pin": PIN}, headers={"X-Real-IP": "10.99.0.1"})).json().get("token", "")
    auth = {"Authorization": f"Bearer {tok}"}

    # ===== hand-over cancel (routine)
    c = await Call().open()
    r, st, _ = await c.say("can I talk to a real person")
    check("asking for a person starts a (simulated) hand-over", st and st["state"] == "handover" and st["mode"] == "handover", r[:50])
    hid = (c.last("handover") or {}).get("id")
    r, st, _ = await c.say("no, don't connect me to anyone, I'm fine")
    check("caller says no -> Hania switches back and keeps talking", st and st["state"] == "listening" and st["mode"] == "normal" and "won't connect you" in r, r[:80])
    check("UI is told the hand-over was cancelled", (c.last("handover") or {}).get("status") == "cancelled")
    async with httpx.AsyncClient(timeout=30) as h:
        hs = {x["id"]: x for x in (await h.get(f"{HTTP}/api/staff/handovers", headers=auth)).json()}
        check("staff console shows it as cancelled", hs.get(hid, {}).get("status") == "cancelled", str(hs.get(hid, {}).get("status")))
        acc = await h.post(f"{HTTP}/api/staff/handovers/{hid}/accept", headers=auth)
        check("accepting a cancelled hand-over is refused", acc.status_code == 409, str(acc.status_code))
    r, st, _ = await c.say("what are the visiting hours?")
    check("conversation continues normally after cancelling", "4 PM to 7 PM" in r and st["mode"] == "normal", r[:60])
    r, st, _ = await c.say("actually can I speak to a person after all")
    check("she can hand over again later", st and st["state"] == "handover", r[:50])
    await c.close()

    # ===== emergency: alert kept, but she keeps talking
    c = await Call().open()
    r, st, _ = await c.say("I have chest pain")
    check("emergency -> alert + 1122 advice", st and st["mode"] == "emergency" and "1122" in r)
    r, st, _ = await c.say("I'm fine, don't call anyone")
    check("emergency alert is NOT silently cancelled; she keeps talking", st and st["mode"] == "normal" and "keep our team alerted" in r, r[:90])
    async with httpx.AsyncClient(timeout=30) as h:
        hs = (await h.get(f"{HTTP}/api/staff/handovers", headers=auth)).json()
        check("staff still see the emergency waiting", any(x["urgency"] == "emergency" and x["status"] == "waiting" for x in hs))
    await c.close()

    # ===== deep hospital knowledge
    c = await Call().open()
    for q, must in [
        ("which doctor sees cardiology patients", "Amina Qasim"), ("how much is the consultation fee", "fifteen hundred"),
        ("do you have an MRI scan", "MRI"), ("where is the blood bank", "blood bank"), ("what time is discharge", "noon"),
        ("which floor is orthopedics on", "first floor"), ("do you have an ambulance service", "1122"), ("do you accept insurance", "insurance"),
        ("how do I get my lab reports", "laboratory counter"), ("is there a pharmacy", "pharmacy"), ("what departments do you have", "Cardiology"),
        ("can I choose my doctor", "doctor"), ("what is the hospital phone number", "number"), ("where is the emergency department", "east side"),
        ("do you have physiotherapy", "physiotherapy"), ("do you have wheelchair access", "ramps"),
    ]:
        r, st, dt = await c.say(q)
        check(f"knows: {q}", must.lower() in r.lower() and "don't have that information" not in r, f"{dt:.1f}s {r[:70]}")
    await c.close()

    # ===== appointment flows
    c = await Call().open()
    await c.say("I'd like to book an appointment")
    await c.say("my name is Ayesha Khan and my date of birth is 12 March 1990")
    await c.say("dermatology")
    r, _, _ = await c.say("day after tomorrow")
    await c.say("the first one")
    r, st, _ = await c.say("yes")
    check("flow: book appointment", "confirmed" in r.lower(), r[:80])
    r, _, _ = await c.say("I want to reschedule my appointment")
    check("flow: reschedule finds the appointment", "would you like to change" in r.lower(), r[:90])
    await c.say("yes")
    r, _, _ = await c.say("tomorrow")
    if "openings" in r:
        await c.say("the second one")
    r3, _, _ = await c.say("yes")
    check("flow: reschedule completes", "confirmed" in r3.lower() or "no openings" in r.lower(), (r3 or r)[:80])
    await c.say("cancel my appointment")
    r, _, _ = await c.say("yes")
    check("flow: cancel appointment", "cancelled" in r.lower(), r[:60])
    await c.close()

    # ===== health talk not auto-handed to staff
    c = await Call().open()
    r, st, _ = await c.say("im feeling sick im like ahving vomit what to do ? its not for diagonose?")
    check("health question -> doctor-style answer, not staff", st and st["state"] == "listening" and "professional doctor" in r, r[:80])
    await c.close()

    # ===== a new message supersedes the previous one
    c = await Call().open()
    n = len(c.caps)
    await c.ws.send(json.dumps({"type": "text", "text": "what are your OPD timings"}))
    await asyncio.sleep(0.15)
    await c.ws.send(json.dumps({"type": "text", "text": "who are you"}))
    t0 = time.perf_counter()
    await c.wait_idle(30)
    await asyncio.sleep(1.0)
    spoken = " ".join(x[1] for x in c.caps[n:] if x[0] == "assistant")
    for _ in range(8):  # keep reading the socket until the answer to the NEW question shows up
        if "virtual assistant" in " ".join(x[1] for x in c.caps[n:] if x[0] == "assistant"):
            break
        await c.wait_idle(3)
    spoken = " ".join(x[1] for x in c.caps[n:] if x[0] == "assistant")
    check("new message supersedes the old one (she answers the NEW question)", "virtual assistant" in spoken and "Hania" in spoken, f"{time.perf_counter() - t0:.1f}s {spoken[-80:]}")
    await c.close()

    # ===== Hindi / Urdu
    c = await Call().open(lang="hi")
    greet = c.caps[0][1] if c.caps else ""
    check("Hindi greeting (Devanagari, testing-agent disclaimer)", DEVA(greet) and "टेस्टिंग" in greet, greet[:60])
    check("Hindi voice audio delivered", c.bytes > 100000, f"{c.bytes} bytes")
    r, st, dt = await c.say("ओपीडी का समय क्या है")
    check("Hindi question -> Hindi answer", DEVA(r), f"{dt:.1f}s {r[:70]}")
    r, st, dt = await c.say("मुझे सीने में दर्द है")
    check("Hindi emergency detected -> Hindi script + hand-over", st and st["mode"] == "emergency" and "एक एक दो दो" in r, r[:70])
    r, st, dt = await c.say("नहीं, मैं ठीक हूँ")
    check("Hindi 'I'm fine' -> keeps alert but continues in Hindi", st and st["mode"] == "normal" and DEVA(r), r[:70])
    await c.close()

    c = await Call().open(lang="en")
    r, st, _ = await c.say("مجھے اپوائنٹمنٹ بک کرنی ہے")
    sw = c.last("language")
    check("Urdu text in an English session -> auto-switches language", sw and sw["lang"] == "ur", str(sw))
    check("Urdu caller is served (not handed to staff)", st and st["state"] != "handover", r[:60])
    await c.close()
    c = await Call().open(lang="en")
    await c.ws.send(json.dumps({"type": "set_language", "lang": "hi"}))
    await asyncio.sleep(0.5)
    r, st, _ = await c.say("आप कौन हैं")
    check("dropdown switch to Hindi works mid-call", DEVA(r) and "हानिया" in r, r[:70])
    await c.close()

    print()
    print("PASSED %d / %d" % (sum(1 for _, ok in results if ok), len(results)))
    bad = [n for n, ok in results if not ok]
    if bad:
        print("FAILED:", bad)


asyncio.run(main())
