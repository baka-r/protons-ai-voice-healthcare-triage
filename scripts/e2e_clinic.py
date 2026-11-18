"""Live checks for the demo-readiness features: accounts and roles, consent/tester role, urgency tiers, age intake,
feedback, doctor review, corrections export, owner dashboard.

    docker compose exec -T agent python - < scripts/e2e_clinic.py
(optionally BASE_WS / BASE_HTTP / ORIGIN / OWNER_PASSWORD env vars to run against a remote deployment)
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
OWNER_PW = os.environ.get("OWNER_PASSWORD", "1234")
results = []
_ip = [int(time.time()) % 200]


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


class Call:
    async def open(self, **start):
        _ip[0] += 1
        h = {"X-Real-IP": f"10.66.{_ip[0] % 250}.{(_ip[0] * 7) % 250}"}
        if ORIGIN:
            h["Origin"] = ORIGIN
        self.ws = await websockets.connect(f"{WS}/ws/call", max_size=None, additional_headers=h)
        self.caps, self.msgs = [], []
        await self.ws.send(json.dumps({"type": "start", "lang": "en", **start}))
        await self.idle()
        return self

    async def idle(self, timeout=90):
        end, spoke = time.time() + timeout, False
        while time.time() < end:
            try:
                m = await asyncio.wait_for(self.ws.recv(), timeout=max(0.1, end - time.time()))
            except (asyncio.TimeoutError, websockets.ConnectionClosed):
                return None
            if isinstance(m, bytes):
                continue
            j = json.loads(m)
            self.msgs.append(j)
            if j["type"] == "caption":
                self.caps.append((j["role"], j["text"]))
            elif j["type"] == "audio_start":
                spoke = True
            elif j["type"] == "state" and j["state"] in ("listening", "handover", "ended") and spoke:
                return j
        return None

    async def say(self, text):
        n = len(self.caps)
        await self.ws.send(json.dumps({"type": "text", "text": text}))
        st = await self.idle()
        return " ".join(c[1] for c in self.caps[n:] if c[0] == "assistant"), st

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
        hdr = {"X-Real-IP": "10.99.7.1"}
        # ---------- accounts and roles
        r = await h.post(f"{HTTP}/api/staff/login", json={"username": "owner", "password": "wrong-password"}, headers=hdr)
        check("wrong owner password is refused", r.status_code == 401)
        r = await h.post(f"{HTTP}/api/staff/login", json={"username": "owner", "password": OWNER_PW}, headers={"X-Real-IP": "10.99.7.2"})
        owner = r.json() if r.status_code == 200 else {}
        check("owner signs in with a named account (admin role)", owner.get("role") == "admin", str(r.status_code))
        oa = {"Authorization": f"Bearer {owner.get('token', '')}"}

        uname = f"dr.test{int(time.time()) % 100000}"
        r = await h.post(f"{HTTP}/api/admin/accounts", json={"username": uname, "name": "Dr Test", "role": "clinician", "password": "short"}, headers=oa)
        check("weak account password is refused", r.status_code == 400)
        r = await h.post(f"{HTTP}/api/admin/accounts", json={"username": uname, "name": "Dr Test", "role": "clinician", "password": "a-long-password-1"}, headers=oa)
        check("owner creates a doctor account", r.status_code == 200, r.text[:80])
        r = await h.post(f"{HTTP}/api/staff/login", json={"username": uname, "password": "a-long-password-1"}, headers={"X-Real-IP": "10.99.7.3"})
        doc = r.json() if r.status_code == 200 else {}
        check("doctor signs in (clinician role)", doc.get("role") == "clinician")
        da = {"Authorization": f"Bearer {doc.get('token', '')}"}
        check("doctor cannot see the owner dashboard", (await h.get(f"{HTTP}/api/owner/stats", headers=da)).status_code == 403)
        check("doctor cannot manage accounts", (await h.get(f"{HTTP}/api/admin/accounts", headers=da)).status_code == 403)
        check("doctor can open the review list", (await h.get(f"{HTTP}/api/review/sessions", headers=da)).status_code == 200)
        pin = await h.post(f"{HTTP}/api/staff/login", json={"pin": os.environ.get("PIN", "1234")}, headers={"X-Real-IP": "10.99.7.4"})
        sa = {"Authorization": f"Bearer {pin.json().get('token', '')}"} if pin.status_code == 200 else {}
        check("desk PIN is support only: no review access", (await h.get(f"{HTTP}/api/review/sessions", headers=sa)).status_code == 403)
        check("no token: review is 401", (await h.get(f"{HTTP}/api/review/sessions")).status_code == 401)
        check("demo scenarios are listed", len((await h.get(f"{HTTP}/api/demo/scenarios")).json()) >= 8)
        st = (await h.get(f"{HTTP}/api/status")).json()
        check("status reports AI busy flag", "llm_busy" in st, str(st))

        # ---------- a mild complaint: interview or doctor chat, with a tier, feedback and a stored transcript
        c = await Call().open(role="qa", consent=True)
        r, _ = await c.say("I have a fever")
        r2, _ = await c.say("30")
        check("health talk gets a disclaimer or the age question", ("how old" in (r + r2).lower()) or ("professional doctor" in (r + r2).lower()), (r + " | " + r2)[:100])
        for a in ("no", "no", "no", "no", "no", "no"):
            if c.last("triage"):
                break
            await c.say(a)
        tri = c.last("triage")
        check("urgency tier is sent to the UI", bool(tri) and tri["tier"] in ("self_care", "see_doctor_soon", "same_day"), str(tri))
        await c.ws.send(json.dumps({"type": "feedback", "rating": "down", "comment": "too long", "text": "test answer"}))
        await c.ws.send(json.dumps({"type": "feedback", "rating": "up"}))
        await asyncio.sleep(1.0)
        sid = (c.last("session") or {}).get("id")
        await c.close()
        await asyncio.sleep(1.5)

        r = await h.get(f"{HTTP}/api/review/sessions", headers=da)
        rows = r.json()
        mine = next((x for x in rows if x["session_id"] == sid), None)
        check("call appears in the doctor review list", mine is not None, f"{len(rows)} rows")
        check("tester role and thumbs are recorded", bool(mine) and mine["role"] == "qa" and mine["thumbs_down"] == 1 and mine["thumbs_up"] == 1, str(mine))
        d = (await h.get(f"{HTTP}/api/review/sessions/{sid}", headers=da)).json() if sid else {}
        asst = [u for u in d.get("utterances", []) if u["speaker"] == "assistant"]
        check("transcript is available to doctors", len(asst) >= 2, f"{len(asst)} assistant lines")
        if asst:
            u = asst[-1]["id"]
            bad = await h.post(f"{HTTP}/api/review/sessions/{sid}/verdict", json={"utterance_id": u, "verdict": "wrong"}, headers=da)
            check("an unsafe/wrong verdict needs a correction", bad.status_code == 400)
            ok = await h.post(f"{HTTP}/api/review/sessions/{sid}/verdict", json={"utterance_id": u, "verdict": "wrong", "correction": "Should advise seeing a doctor today.", "expected_tier": "same_day"}, headers=da)
            check("doctor saves a verdict", ok.status_code == 200, ok.text[:80])
            exp = (await h.get(f"{HTTP}/api/review/export", headers=da)).json()
            check("the correction is exported as a test case", any(e["expected_tier"] == "same_day" and "doctor today" in e["doctor_correction"] for e in exp))
            d2 = (await h.get(f"{HTTP}/api/review/sessions/{sid}", headers=da)).json()
            check("verdict is shown back on the call", any(v["verdict"] == "wrong" for v in d2["reviews"]))

        # ---------- an emergency hand-over carries a clinical brief for staff
        c = await Call().open(role="doctor", consent=True)
        r, st = await c.say("I have chest pain")
        check("emergency -> hand-over", st and st["state"] == "handover", r[:60])
        await asyncio.sleep(1.0)
        hs = (await h.get(f"{HTTP}/api/staff/handovers", headers=sa)).json()
        mine_h = next((x for x in hs if x["session_id"] == (c.last("session") or {}).get("id")), None)
        det = (await h.get(f"{HTTP}/api/staff/handovers/{mine_h['id']}", headers=sa)).json() if mine_h else {}
        check("staff see a clinical brief with the emergency tier and reason", (det.get("brief") or {}).get("tier") == "emergency" and bool((det.get("brief") or {}).get("reasons")), str(det.get("brief"))[:120])
        await c.close()

        c = await Call().open()
        r, st = await c.say("my baby has a fever")
        check("a baby with fever is not left to home care", st and (st["state"] == "handover" or "same" in r.lower() or "doctor" in r.lower()), r[:90])
        await c.close()

        c = await Call().open()
        r, st = await c.say("I have chest pain")
        tri = c.last("triage")
        check("emergency words: emergency tier sent to the UI", bool(tri) and tri["tier"] == "emergency", str(tri))
        await c.close()

        # ---------- owner dashboard
        s = (await h.get(f"{HTTP}/api/owner/stats?days=1", headers=oa)).json()
        check("owner dashboard has calls, tiers, feedback and speed", s.get("calls", 0) >= 3 and s.get("tiers") and s.get("feedback", {}).get("down", 0) >= 1 and "ai" in s, str({k: s.get(k) for k in ("calls", "tiers", "feedback")}))
        check("dashboard counts testers by role", s.get("testers", {}).get("qa", 0) >= 1, str(s.get("testers")))
        rs = await h.post(f"{HTTP}/api/admin/demo/reset", headers=oa)
        check("owner can reset the demo queue", rs.status_code == 200)
        await h.post(f"{HTTP}/api/admin/accounts/{uname}", json={"active": False}, headers=oa)  # leave no usable test account behind
        check("test doctor account is deactivated and can no longer sign in", (await h.post(f"{HTTP}/api/staff/login", json={"username": uname, "password": "a-long-password-1"}, headers={"X-Real-IP": "10.99.7.9"})).status_code == 401)
        ver = (await h.get(f"{HTTP}/api/audit/verify", headers=oa)).json()
        check("audit chain still verifies", ver.get("ok") is True, str(ver))

    print()
    print("PASSED %d / %d" % (sum(1 for _, ok in results if ok), len(results)))
    bad = [n for n, ok in results if not ok]
    if bad:
        print("FAILED:", bad)


asyncio.run(main())
