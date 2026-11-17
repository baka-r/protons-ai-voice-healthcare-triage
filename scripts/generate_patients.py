"""Deterministically generate SYNTHETIC patients for the mock EMR (no real people).

    python scripts/generate_patients.py            # writes mock-emr/patients.json

Includes deliberate edge cases: shared birthdays, near-identical names, single names, hyphenated names.
Everything is invented from name lists with a fixed random seed, so the file is reproducible.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

SEED = 20261118
FIRST = ["Ayesha", "Hamza", "Fatima", "Usman", "Sara", "Bilal", "Hira", "Zain", "Maryam", "Ahmed", "Noor", "Imran", "Sana", "Kamran",
         "Amna", "Faisal", "Rabia", "Talha", "Iqra", "Omar", "Mehwish", "Danish", "Laiba", "Saad", "Zoya", "Hassan", "Areeba", "Junaid",
         "Khadija", "Rayan", "Mahnoor", "Shahid", "Anum", "Taimoor", "Esha", "Waqas", "Kiran", "Adeel", "Dua", "Moiz"]
LAST = ["Khan", "Ali", "Noor", "Raza", "Malik", "Sheikh", "Butt", "Chaudhry", "Qureshi", "Hussain", "Siddiqui", "Ansari", "Mirza", "Javed", "Iqbal", "Rauf"]

# the five identities used in the README / tests are kept stable
FIXED = [
    ("P-1001", "Ayesha Khan", "1990-03-12"), ("P-1002", "Hamza Ali", "1985-07-21"), ("P-1003", "Fatima Noor", "2001-11-05"),
    ("P-1004", "Usman Raza", "1978-01-30"), ("P-1005", "Sara Malik", "1995-09-18"),
]
# edge cases: same birthday + near-identical names (must NOT be guessed), single name, hyphenated surname
EDGE = [
    ("P-1101", "Ali Khan", "1992-02-02"), ("P-1102", "Aly Khan", "1992-02-02"),
    ("P-1103", "Noor Fatima", "1988-08-08"), ("P-1104", "Zara Ahmed-Khan", "1999-12-25"), ("P-1105", "Bibi", "1950-05-05"),
]


def main() -> None:
    rnd = random.Random(SEED)
    patients = [{"id": i, "name": n, "birthDate": d} for i, n, d in FIXED + EDGE]
    used = {p["name"] for p in patients}
    n = 1200
    while len(patients) < 50:
        name = f"{rnd.choice(FIRST)} {rnd.choice(LAST)}"
        if name in used:
            continue
        used.add(name)
        year = rnd.randint(1936, 2024)
        patients.append({"id": f"P-{n}", "name": name, "birthDate": f"{year}-{rnd.randint(1, 12):02d}-{rnd.randint(1, 28):02d}"})
        n += 1
    payload = json.dumps({"_note": "SYNTHETIC patients. Not real people.", "patients": patients}, indent=1)
    root = Path(__file__).resolve().parent.parent
    for out in (root / "mock-emr" / "patients.json", root / "agent" / "seed" / "patients.json"):
        out.write_text(payload, encoding="utf-8")
        print(f"wrote {len(patients)} synthetic patients -> {out}")


if __name__ == "__main__":
    main()
