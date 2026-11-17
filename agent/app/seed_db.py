"""Reproducible database seeder (idempotent).

    docker compose run --rm agent python -m app.seed_db

Loads: roles + demo staff user, synthetic patient links, synthetic practitioners, approved knowledge
(documents/versions/chunks incl. the excluded drafts), and the ~1k synthetic evaluation cases.
ALL DATA IS SYNTHETIC. clinical_review is PENDING - nothing here is clinically validated.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path

from app.config import get_settings
from app.db import Store
from seed.generate_cases import all_cases


async def main() -> None:
    s = get_settings()
    store = Store(s.database_url)
    store.init()
    patients = json.loads((Path("seed") / "patients.json").read_text(encoding="utf-8"))["patients"]
    dept_names = ["Cardiology", "General Medicine", "Orthopedics", "Pediatrics", "Gynecology", "Dermatology", "ENT", "Ophthalmology"]
    print("reference data:", store.seed_reference_data(patients, dept_names))

    cases = [{**c.__dict__, "forbid": list(c.forbid), "expect_rules": c.expect_rules} for c in all_cases()]
    print("eval cases upserted:", store.upsert_eval_cases(cases))

    from app.services.rag import parse_markdown, select_eligible
    files = sorted(Path(s.knowledge_dir).glob("*.md"))
    docs = select_eligible([parse_markdown(f) for f in files], date.today())
    store.record_knowledge(docs)
    print(f"knowledge versions recorded: {len(docs)} (included: {sum(d.included for d in docs)})")
    store.audit("system", "database_seeded", {"patients": len(patients), "eval_cases": len(cases), "knowledge_versions": len(docs)})
    print("audit chain:", store.verify_audit())


if __name__ == "__main__":
    asyncio.run(main())
