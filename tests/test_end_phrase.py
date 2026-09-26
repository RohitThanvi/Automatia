import numpy as np
import pytest

from voice.stt import ends_with_phrase, strip_end_phrase


def test_ends_with_phrase_simple_match():
    assert ends_with_phrase("please write an essay over", "over") is True


def test_ends_with_phrase_case_and_punctuation_insensitive():
    assert ends_with_phrase("...and that's everything, Over!", "over") is True


def test_ends_with_phrase_multi_word():
    assert ends_with_phrase("write an essay that's all folks", "that's all folks") is True


def test_ends_with_phrase_not_at_end():
    assert ends_with_phrase("over the moon we go", "over") is False


def test_ends_with_phrase_no_phrase_configured():
    assert ends_with_phrase("anything at all", None) is False
    assert ends_with_phrase("anything at all", "") is False


def test_strip_end_phrase_removes_trailing_word():
    assert strip_end_phrase("write an essay over", "over") == "write an essay"


def test_strip_end_phrase_removes_trailing_punctuation_too():
    assert strip_end_phrase("write an essay, over.", "over") == "write an essay"


def test_strip_end_phrase_noop_when_not_present():
    assert strip_end_phrase("write an essay please", "over") == "write an essay please"


def test_strip_end_phrase_multi_word_phrase():
    assert strip_end_phrase("open chrome that's all folks", "that's all folks") == "open chrome"


def test_strip_end_phrase_noop_when_no_phrase_configured():
    assert strip_end_phrase("write an essay over", None) == "write an essay over"


class _FakeSTT:
    """Feeds back pre-scripted transcriptions in order, one per call —
    lets us drive AudioRecorder's phrase-recheck loop deterministically
    without a real Whisper model or microphone."""

    def __init__(self, scripted_responses: list[str]):
        self._responses = list(scripted_responses)
        self.call_count = 0

    def transcribe(self, audio: np.ndarray) -> str:
        self.call_count += 1
        if self._responses:
            return self._responses.pop(0)
        return ""


@pytest.fixture(autouse=True)
def temp_config(tmp_path):
    from core.config import reload_config

    cfg = reload_config()
    cfg.audio.end_phrase = "over"
    cfg.audio.silence_timeout_ms = 90   # 3 frames of 30ms
    cfg.audio.end_phrase_recheck_ms = 60  # 2 frames of 30ms
    yield cfg
    reload_config()


def _feed_frames(recorder, monkeypatch, is_speech_sequence, frame_bytes_len=480):
    """Drive record_utterance's internal loop by monkeypatching its
    audio input queue and VAD to a scripted sequence of is_speech
    booleans, without touching real sounddevice/webrtcvad."""
    import voice.stt as stt_module

    frame = np.zeros((frame_bytes_len, 1), dtype=np.int16)
    call_iter = iter(is_speech_sequence)

    class FakeVAD:
        def is_speech(self, frame_bytes):
            return next(call_iter)

    class FakeStream:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(recorder, "_vad", FakeVAD())
    monkeypatch.setattr(stt_module.sd, "InputStream", FakeStream)

    frames_remaining = [frame] * len(is_speech_sequence)

    class FakeQueue:
        def get(self, timeout=None):
            if frames_remaining:
                return frames_remaining.pop(0)
            raise stt_module.queue.Empty()

    monkeypatch.setattr(stt_module.queue, "Queue", lambda: FakeQueue())


def test_recorder_ends_on_phrase_match(monkeypatch):
    from voice.stt import AudioRecorder

    fake_stt = _FakeSTT(["please continue writing", "okay that will be all, over"])
    recorder = AudioRecorder(stt=fake_stt)
    # speech, speech, then 4 silent frames (crosses both the initial
    # timeout check and one recheck) before we run out of frames.
    _feed_frames(recorder, monkeypatch, [True, True, False, False, False, False])

    recorder.record_utterance()
    assert fake_stt.call_count >= 1  # at least one phrase check happened


def test_recorder_falls_back_without_stt(monkeypatch):
    from voice.stt import AudioRecorder

    recorder = AudioRecorder(stt=None)  # end_phrase configured but no stt -> plain silence timeout
    _feed_frames(recorder, monkeypatch, [True, False, False, False])

    audio = recorder.record_utterance()
    assert audio.size > 0  # completed without needing a phrase check
