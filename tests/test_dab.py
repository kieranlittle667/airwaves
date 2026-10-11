import queue
import sys
import time

import pytest

from airwaves import dab
import io
import wave
import numpy as np


def test_scanner_parses_dab_and_dabplus():
    for codec in ("DAB", "DAB+"):
        service = dab.parse_service(
            f"audioservice;BBC Radio 4     ;12B;C224;8;360;72;96;{codec};0;EEP 3-A;1/2;English;"
        )
        assert service == dab.Service("BBC Radio 4", "12B", 0xC224, codec, 96)
    for line in ("Waiting for time sync 4", "audioservice;", "audioservice;x;12B;BAD-ID;0;0;0;96;DAB+", ""):
        assert dab.parse_service(line) is None


def test_arguments_preserve_service_names_without_shell_execution():
    name = 'BBC Radio 4; echo "not a command"'
    command = dab.playback_command(sys.executable, "12b", name)
    assert command[command.index("-P") + 1] == name
    assert command[command.index("-C") + 1] == "12B"
    with pytest.raises(ValueError):
        dab.playback_command(sys.executable, "FM", "BBC")
    with pytest.raises(ValueError):
        dab.playback_command(sys.executable, "12B", " ")
    with pytest.raises(FileNotFoundError):
        dab.scan_command("airwaves-nonexistent-scanner")


def events_until_exit(decoder):
    events = []
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            event = decoder.events.get(timeout=0.1)
        except queue.Empty:
            continue
        events.append(event)
        if event[0] == "exit":
            return events
    pytest.fail("Decoder did not report exit")


def test_real_process_delivers_scan_results_and_failure(tmp_path):
    script = tmp_path / "decoder.py"
    script.write_text("print('audioservice;Test;11D;ABCD;1;0;1;64;DAB+;')\nraise SystemExit(22)\n")
    decoder = dab.Decoder()
    try:
        decoder.start([sys.executable, str(script)], "scan")
        events = events_until_exit(decoder)
        assert ("service", dab.Service("Test", "11D", 0xABCD, "DAB+", 64)) in events
        assert events[-1] == ("exit", 22)
    finally:
        decoder.stop()
    assert decoder.process is None


def test_stop_releases_process_before_restart(tmp_path):
    script = tmp_path / "decoder.py"
    script.write_text("import time\nprint('ready', flush=True)\ntime.sleep(60)\n")
    decoder = dab.Decoder()
    try:
        decoder.start([sys.executable, str(script)])
        first = decoder.process
        assert decoder.events.get(timeout=10) == ("log", "ready")
        decoder.start([sys.executable, "-c", "print('second')"])
        assert first.poll() is not None
        events = events_until_exit(decoder)
        assert events == [("log", "second"), ("exit", 0)]
    finally:
        decoder.stop()


def test_failed_launch_and_repeated_stop_are_safe():
    decoder = dab.Decoder()
    with pytest.raises(OSError):
        decoder.start(["airwaves-nonexistent-decoder"])
    decoder.stop()
    decoder.stop()


def test_pcm_protocol_handles_short_reads_and_rejects_invalid_data():
    class Fragmented(io.BytesIO):
        def read(self, size=-1):
            return super().read(min(size, 3))
    pcm = b"\x01\x00\xff\xff" * 100
    payload = dab.PCM_HEADER.pack(b"AWPC", 24000, len(pcm)) + pcm
    stream = Fragmented(payload)
    assert dab.read_pcm_frame(stream) == (24000, pcm)
    assert dab.read_pcm_frame(stream) is None
    with pytest.raises(ValueError, match="incomplete"):
        dab.read_pcm_frame(io.BytesIO(payload[:-1]))
    with pytest.raises(ValueError, match="protocol"):
        dab.read_pcm_frame(io.BytesIO(dab.PCM_HEADER.pack(b"BAD!", 48000, 4) + b"1234"))


def test_dab_records_before_mute_and_separates_diagnostics(tmp_path):
    from airwaves.recording import Recording
    recorded = tmp_path / "dab.wav"
    script = tmp_path / "pcm.py"
    script.write_text("import sys, struct\n"
                      "print('decoder diagnostic', file=sys.stderr, flush=True)\n"
                      "pcm = struct.pack('<hh', 8192, -8192) * 2400\n"
                      "sys.stdout.buffer.write(struct.pack('<4sII', b'AWPC', 24000, len(pcm)) + pcm)\n")
    writes = []
    class Player:
        def write(self, audio, rate, gain):
            writes.append((rate, gain, len(audio)))
        def close(self):
            writes.append("closed")
    session = Recording()
    session.start(str(recorded))
    decoder = dab.Decoder()
    decoder.player_factory = Player
    decoder.on_audio = session.write
    decoder.muted = True
    try:
        decoder.start([sys.executable, str(script)], "audio")
        events = events_until_exit(decoder)
        assert ("log", "decoder diagnostic") in events
        assert ("audio_ready", 24000) in events
    finally:
        decoder.stop()
        session.stop()
    assert writes == [(24000, 0, 2400), "closed"]
    with wave.open(str(recorded)) as file:
        assert (file.getframerate(), file.getnframes()) == (24000, 2400)
        audio = np.frombuffer(file.readframes(1), dtype="<i2")
        assert audio.tolist() == [8191, -8191]
