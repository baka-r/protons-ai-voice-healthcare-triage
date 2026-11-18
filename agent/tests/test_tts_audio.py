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


# ---------------------------------------------------------------- service numbers are read digit by digit
def test_service_numbers_are_spoken_as_digits():
    from app.services.tts import say_digits, spoken

    assert say_digits("1122") == "double one double two"
    assert say_digits("115") == "double one five"
    assert say_digits("999") == "triple nine"
    assert spoken("please call 1122 right now") == "please call double one double two right now"
    assert spoken("In an emergency, call 1122.") == "In an emergency, call double one double two."
    assert spoken("call 911, then 115") == "call nine double one, then double one five"
    # ordinary numbers are left alone
    assert spoken("Come in 15 minutes") == "Come in 15 minutes"
    assert spoken("The fee is 11220 rupees") == "The fee is 11220 rupees"
    assert spoken("it costs 1,122 rupees") == "it costs 1,122 rupees"
    assert spoken("it is 3.1122") == "it is 3.1122"


def test_lines_with_a_service_number_use_a_new_cache_version():
    from app.config import Settings
    from app.services.tts import TTS

    t = TTS(Settings())
    plain = t._key("hello there")
    assert plain != t._key("call 1122 now")
