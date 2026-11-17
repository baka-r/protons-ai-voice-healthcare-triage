from datetime import date

import pytest

from app.db import chain_hash
from app.safety import scripts
from app.safety.guard import check_output
from app.safety.pii import mask
from app.services.rag import DocVersion, select_eligible, parse_markdown
from app.services.tts import split_sentences


@pytest.mark.parametrize("text", [
    "Take 500 mg every six hours", "You should take two tablets", "It is probably an infection", "You have diabetes",
    "Try some paracetamol", "This may be a diagnosis of cancer", "you should stop your insulin",
])
def test_guard_blocks_medical_language(text):
    assert not check_output(text).ok


@pytest.mark.parametrize("text", [
    "Our outpatient clinics are open Monday to Saturday from 9 AM to 5 PM.",
    "Bus route twelve stops outside the main gate.", "Please bring your national ID card and previous reports.",
])
def test_guard_allows_plain_information(text):
    assert check_output(text).ok


def test_every_fixed_script_is_speakable_and_safe():
    for key, text in scripts.all_fixed().items():
        assert text.strip()
        # fixed scripts are reviewed text; they must still never contain dosage/drug language
        v = check_output(text)
        assert v.ok or v.reason == "diagnosis", f"{key}: {v.reason}"


def test_pii_masking():
    out = mask("call me on +92 300 1234567, CNIC 35202-1234567-1, mail a.b@x.com, born 12/03/1990")
    assert "1234567" not in out and "@" not in out and "12/03/1990" not in out


def _doc(doc_id, version, status="approved", expires=None):
    return DocVersion(doc_id=doc_id, title=doc_id, version=version, approval_status=status, approved_by="x", category="c", expires=expires)


def test_only_approved_current_latest_documents_are_eligible():
    docs = select_eligible([
        _doc("hours", 1), _doc("hours", 2), _doc("draft-guide", 1, status="draft"),
        _doc("flu", 1, expires="2025-12-31"), _doc("parking", 1),
    ], date(2026, 11, 18))
    by = {(d.doc_id, d.version): d for d in docs}
    assert by[("hours", 2)].included
    assert not by[("hours", 1)].included and "superseded" in by[("hours", 1)].exclusion_reason
    assert not by[("draft-guide", 1)].included
    assert not by[("flu", 1)].included and "expired" in by[("flu", 1)].exclusion_reason
    assert by[("parking", 1)].included


def test_knowledge_files_parse_and_exclusions_hold():
    from pathlib import Path
    files = sorted(Path("knowledge").glob("*.md"))
    docs = select_eligible([parse_markdown(f) for f in files], date(2026, 11, 18))
    included = {(d.doc_id, d.version) for d in docs if d.included}
    assert ("hospital-hours", 2) in included
    assert ("hospital-hours", 1) not in included
    assert ("medication-guide", 1) not in included
    assert ("flu-clinic", 1) not in included
    assert all(d.chunks for d in docs)
    # approved text must itself pass the output guard
    for d in docs:
        if d.included:
            for _, text in d.chunks:
                assert check_output(text).ok, f"{d.doc_id}: {text}"


def test_audit_hash_chain_detects_tampering():
    h1 = chain_hash("0" * 64, "t1", "system", "call_started", {"a": 1})
    h2 = chain_hash(h1, "t2", "system", "call_ended", {"a": 2})
    assert h2 != chain_hash(h1, "t2", "system", "call_ended", {"a": 3})
    assert h2 != chain_hash("f" * 64, "t2", "system", "call_ended", {"a": 2})


def test_sentence_splitter_joins_tiny_fragments():
    assert split_sentences("Hi. This is a longer second sentence here.") == ["Hi. This is a longer second sentence here."]
    assert len(split_sentences("This is the first full sentence. This is the second full sentence.")) == 2
