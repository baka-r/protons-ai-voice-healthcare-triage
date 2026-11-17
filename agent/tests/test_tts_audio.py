import numpy as np

from app.services.tts import HOLD_BYTES, SAMPLE_RATE, pause_ms, silence, trim_pcm


def tone(ms, amp=8000):
    t = np.arange(int(SAMPLE_RATE * ms / 1000)) / SAMPLE_RATE
    return (np.sin(2 * np.pi * 220 * t) * amp).astype(np.int16).tobytes()


def test_trim_removes_padding_but_keeps_speech():
    pcm = silence(60) + tone(500) + silence(400)
    out = trim_pcm(pcm)
    ms = len(out) / 2 / SAMPLE_RATE * 1000
    assert 520 <= ms <= 580, ms  # ~500 ms speech + 15 ms lead + 40 ms tail
    assert len(trim_pcm(silence(200))) == len(silence(200))  # all-quiet input untouched


def test_pauses_depend_on_punctuation():
    assert pause_ms("It is open.") > pause_ms("On Thursday,") > 0
    assert pause_ms("Which time suits you?") == pause_ms("Done.")


def test_silence_length():
    assert len(silence(100)) == int(SAMPLE_RATE * 0.1) * 2 and HOLD_BYTES % 2 == 0
