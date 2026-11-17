"""The pre-rendered phrase vocabulary must cover exactly what the booking flow says, or the cache is useless."""
from datetime import timedelta

from app.dialog import rules
from app.dialog.engine import phrase_vocab, time_chunks
from tests.test_engine import mk, A
from app.dialog.session import Session


async def test_every_booking_chunk_is_in_the_prewarmed_vocabulary():
    eng, llm, emr = mk(A(intent="provide_info"))
    vocab = set(phrase_vocab(["Cardiology", "General Medicine", "ENT"], days=3))
    s = Session(id="t", state="AWAIT_DEPT", verified=True, patient={"id": "P-1001", "name": "Ayesha Khan"})
    seen = []
    for say, ai in [("cardiology please", A(department="Cardiology")), ("tomorrow", A(date=emr.tomorrow)), ("the first one", A(time="09:00")), ("yes", None)]:
        llm.analysis = ai
        r = await eng.handle(s, say)
        for line in r.lines:
            if line.chunks:
                seen += line.chunks
    variable = [c for c in seen if c not in vocab]
    # only fixed sentences (not date/time/dept based) may be absent, and they are covered by the fixed-script cache
    assert all(c in ("What date would you like to come in?", "Which time suits you?", "Shall I confirm that?", "Please arrive fifteen minutes early.")
               for c in variable), variable


def test_time_chunks_shapes():
    assert time_chunks(["09:00"]) == ["9:00 AM."]
    assert time_chunks(["09:00", "10:30"]) == ["9:00 AM,", "and 10:30 AM."]
    assert time_chunks(["09:00", "09:30", "14:00"]) == ["9:00 AM,", "9:30 AM,", "and 2:00 PM."]
