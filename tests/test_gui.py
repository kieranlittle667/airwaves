"""Native GUI smoke and receiver handoff checks; no radio hardware required."""
from types import SimpleNamespace

import pytest

wx = pytest.importorskip("wx")
from airwaves import gui


@pytest.fixture
def frame(tmp_path, monkeypatch, wx_app):
    monkeypatch.chdir(tmp_path)
    window = gui.RadioFrame()
    window.timer.Stop()
    yield window
    if window.pending:
        window.pending[0].result(timeout=10)
    window.stop_all()
    window.worker.shutdown()
    if window and not window.IsBeingDeleted():
        window.Destroy()
    wx_app.ProcessPendingEvents()
    wx_app.Yield()


@pytest.fixture(scope="session")
def wx_app():
    app = wx.GetApp() or wx.App(False)
    yield app
    app.ProcessPendingEvents()
    app.Yield()


def finish(frame):
    frame.pending[0].result(timeout=10)
    frame.tick(None)


def test_native_controls_and_shared_preset_format(frame):
    assert frame.pages.GetPageCount() == 2
    assert frame.frequency.GetName() == "Frequency (MHz)"
    assert frame.station_list.GetName() == "Discovered stations"
    from airwaves import sdr
    frame.sdr = sdr
    frame.receiver = SimpleNamespace(freq_mhz=99.9, hd_program=1, stop=lambda: None)
    frame.save_preset(None)
    assert gui.config.presets() == {1: "99.9 HD2"}


def test_dab_releases_analog_before_launch(frame, monkeypatch):
    calls = []
    frame.receiver = SimpleNamespace(stop=lambda: calls.append("analog stopped"))
    frame.decoder.start = lambda command, mode="play": calls.append("dab started")
    monkeypatch.setattr(gui.dab, "playback_command", lambda *args: ["test"])
    frame.play_dab()
    finish(frame)
    assert calls == ["analog stopped", "dab started"]
    assert frame.receiver is None


def test_stopping_receiver_finalizes_recording(frame, tmp_path):
    import wave
    import numpy as np
    path = tmp_path / "analog.wav"
    frame.receiver = SimpleNamespace(stop=lambda: None)
    frame.recording.start(str(path), 48000)
    frame.recording.write(np.full((4800, 2), 0.2), 48000)
    frame.stop_all()
    with wave.open(str(path)) as file:
        assert file.getnframes() == 4800
    assert not frame.recording.active


def test_close_during_operation_stops_receiver_after_completion(frame):
    import threading
    entered, release = threading.Event(), threading.Event()
    stopped = []
    def delayed_start():
        entered.set()
        assert release.wait(10)
        frame.receiver = SimpleNamespace(stop=lambda: stopped.append(True))
    frame.submit(delayed_start)
    assert entered.wait(10)
    frame.close(SimpleNamespace(CanVeto=lambda: True, Veto=lambda: None))
    release.set()
    finish(frame)
    assert frame.closing
    finish(frame)
    assert stopped == [True]
