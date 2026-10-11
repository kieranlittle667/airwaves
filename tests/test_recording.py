import wave

import numpy as np
import pytest

from airwaves.recording import Recording
from airwaves.audio import Resampler


@pytest.mark.parametrize("rate", [16000, 24000, 32000, 48000])
def test_recording_keeps_native_rate_duration_and_samples(tmp_path, rate):
    path = tmp_path / "station.wav"
    session = Recording()
    session.start(str(path))
    samples = np.tile(np.array([[0.25, -0.5]], dtype=np.float32), (rate // 10, 1))
    session.write(samples, rate)
    session.stop()
    with wave.open(str(path)) as file:
        assert (file.getframerate(), file.getnchannels(), file.getnframes()) == (rate, 2, rate // 10)
        audio = np.frombuffer(file.readframes(rate), dtype="<i2").reshape(-1, 2)
        assert audio[0].tolist() == [8191, -16383]
    assert not session.active


def test_rate_change_reports_error_and_preserves_valid_wav(tmp_path):
    path = tmp_path / "station.wav"
    session = Recording()
    session.start(str(path))
    session.write(np.zeros((100, 2)), 24000)
    session.write(np.zeros((100, 2)), 48000)
    assert "sample rate changed" in str(session.errors.get())
    session.stop()
    with wave.open(str(path)) as file:
        assert file.getframerate() == 24000
        assert file.getnframes() == 100


def test_mp3_recording_finishes_encoder(tmp_path):
    path = tmp_path / "station.mp3"
    session = Recording()
    session.start(str(path), 48000)
    session.write(np.zeros((4800, 2)), 48000)
    session.stop()
    assert path.read_bytes().startswith(b"\xff")
    assert path.stat().st_size > 1000


def test_no_signal_and_failed_destination(tmp_path):
    session = Recording()
    path = tmp_path / "silence.wav"
    session.start(str(path))
    assert "Waiting for decoded audio" in session.describe()
    session.stop()
    assert path.stat().st_size == 0
    with pytest.raises(OSError):
        session.start(str(tmp_path / "missing" / "station.wav"))
    assert not session.active
    with pytest.raises(ValueError):
        session.start(str(tmp_path / "station.txt"))


def test_playback_resampling_is_independent_of_block_boundaries():
    audio = np.column_stack((np.linspace(-0.5, 0.5, 2400), np.linspace(0.5, -0.5, 2400)))
    whole = Resampler(24000, 48000).process(audio)
    resampler = Resampler(24000, 48000)
    split = np.concatenate([resampler.process(block) for block in np.array_split(audio, 7)])
    assert len(whole) == 4800
    assert np.allclose(whole, split)
