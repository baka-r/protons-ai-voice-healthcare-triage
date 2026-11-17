"""Client for the (mock) hospital EMR. The EMR stays the master record."""
from __future__ import annotations

import logging

import httpx
from rapidfuzz import fuzz

from app.config import Settings
from app.safety.text import normalize

log = logging.getLogger("emr")


class EMR:
    def __init__(self, settings: Settings):
        self.http = httpx.AsyncClient(base_url=settings.emr_url, timeout=httpx.Timeout(4.0, connect=2.0))
        self._departments: list[dict] | None = None

    async def healthy(self) -> bool:
        try:
            return (await self.http.get("/health")).status_code == 200
        except Exception:
            return False

    async def departments(self) -> list[dict]:
        if self._departments is None:
            r = await self.http.get("/fhir/Department")
            r.raise_for_status()
            self._departments = r.json()
        return self._departments

    async def find_patient(self, name: str, dob_iso: str) -> dict | None:
        """Match on exact date of birth, then fuzzy-match the spoken name locally."""
        r = await self.http.get("/fhir/Patient", params={"birthdate": dob_iso})
        r.raise_for_status()
        want = normalize(name)
        scored = sorted(((fuzz.token_sort_ratio(want, normalize(p["name"])), p) for p in r.json()), key=lambda x: -x[0])
        if not scored or scored[0][0] < 84:
            return None
        # Two patients with the same date of birth and near-identical names: only an (almost) exact match is accepted,
        # because a speech-recognition slip must never verify the wrong person. Otherwise: no match -> staff.
        if len(scored) > 1 and scored[1][0] >= 70 and scored[0][0] < 97:
            return None
        return scored[0][1]

    async def slots(self, dept_id: str, date_iso: str) -> list[dict]:
        r = await self.http.get("/fhir/Slot", params={"department": dept_id, "date": date_iso})
        r.raise_for_status()
        return r.json()

    async def next_available(self, dept_id: str, after_iso: str) -> str | None:
        r = await self.http.get("/fhir/Slot/next", params={"department": dept_id, "after": after_iso})
        r.raise_for_status()
        return r.json().get("date")

    async def appointments(self, patient_id: str) -> list[dict]:
        r = await self.http.get("/fhir/Appointment", params={"patient": patient_id})
        r.raise_for_status()
        return r.json()

    async def book(self, patient_id: str, slot_id: str) -> dict | None:
        r = await self.http.post("/fhir/Appointment", json={"patient": patient_id, "slot": slot_id})
        if r.status_code == 409:
            return None
        r.raise_for_status()
        return r.json()

    async def cancel(self, appointment_id: str) -> bool:
        r = await self.http.post(f"/fhir/Appointment/{appointment_id}/cancel")
        return r.status_code == 200
