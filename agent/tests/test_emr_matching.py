"""Identity matching must never guess between near-identical patients who share a birthday."""
import httpx

from app.config import Settings
from app.services.emr import EMR

PATIENTS = {
    "1992-02-02": [{"id": "P-1101", "name": "Ali Khan", "birthDate": "1992-02-02"}, {"id": "P-1102", "name": "Aly Khan", "birthDate": "1992-02-02"}],
    "1990-03-12": [{"id": "P-1001", "name": "Ayesha Khan", "birthDate": "1990-03-12"}],
}


def make_emr() -> EMR:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=PATIENTS.get(request.url.params["birthdate"], []))

    emr = EMR(Settings())
    emr.http = httpx.AsyncClient(base_url="http://emr", transport=httpx.MockTransport(handler))
    return emr


async def test_exact_match_among_twins_is_accepted():
    p = await make_emr().find_patient("Ali Khan", "1992-02-02")
    assert p and p["id"] == "P-1101"
    p = await make_emr().find_patient("Aly Khan", "1992-02-02")
    assert p and p["id"] == "P-1102"


async def test_speech_slip_among_twins_is_never_guessed():
    for heard in ("Alee Khan", "Ally Khan", "Ali Kan", "Aliy Khan"):
        assert await make_emr().find_patient(heard, "1992-02-02") is None, heard


async def test_normal_fuzzy_match_when_no_twin():
    assert (await make_emr().find_patient("Ayesha Kahn", "1990-03-12"))["id"] == "P-1001"  # small mishearing, no near-twin
    assert await make_emr().find_patient("Ayesha Khan", "1990-03-13") is None  # wrong birthday
    assert await make_emr().find_patient("Somebody Else", "1990-03-12") is None
