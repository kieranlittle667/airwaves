"""Optional DAB/DAB+ reception using the Airwaves dab-cmdline PCM adapter.

The decoder owns USB and audio. No shell, native library ABI, or bundled
decoder is required. See docs/desktop-ui.md for the supported backend.
"""

import argparse
import csv
import io
import os
import queue
import shutil
import subprocess
import struct
import threading
from dataclasses import dataclass

PCM_HEADER = struct.Struct("<4sII")


def read_exact(stream, size, allow_eof=False):
    data = bytearray()
    while len(data) < size:
        chunk = stream.read(size - len(data))
        if not chunk:
            if not data and allow_eof:
                return None
            raise ValueError("DAB decoder sent an incomplete audio frame.")
        data.extend(chunk)
    return bytes(data)


def read_pcm_frame(stream):
    header = read_exact(stream, PCM_HEADER.size, allow_eof=True)
    if header is None:
        return None
    magic, rate, size = PCM_HEADER.unpack(header)
    if magic != b"AWPC" or not 8000 <= rate <= 192000 or not 0 < size <= 4 * 1024 * 1024 or size % 4:
        raise ValueError("Unsupported DAB audio protocol. Select airwaves-dab-rtlsdr, not an upstream example executable.")
    return rate, read_exact(stream, size)


class AudioPlayer:
    """Play native-rate DAB audio at 48 kHz through the local sound device."""

    def __init__(self):
        import pyaudio
        self.audio = pyaudio.PyAudio()
        try:
            self.stream = self.audio.open(format=pyaudio.paFloat32, channels=2,
                                          rate=48000, output=True)
        except Exception:
            self.audio.terminate()
            raise
        self.resampler = None

    def write(self, audio, rate, gain):
        from .audio import Resampler
        if self.resampler is None or self.resampler.in_rate != rate:
            self.resampler = Resampler(rate, 48000)
        samples = self.resampler.process(audio)
        self.stream.write((samples * gain).tobytes())

    def close(self):
        try:
            self.stream.close()
        finally:
            self.audio.terminate()


# Band III blocks supported by the decoder's band-handler table.
CHANNELS = tuple(f"{number}{letter}" for number in range(5, 14)
                 for letter in ("ABCDEF" if number == 13 else "ABCD"))


@dataclass(frozen=True)
class Service:
    name: str
    channel: str
    service_id: int
    codec: str
    bitrate: int


def parse_service(line):
    """Parse the upstream scanner's semicolon format; ignore diagnostics."""
    fields = next(csv.reader([line], delimiter=";"), [])
    if len(fields) < 9 or fields[0].strip().lower() != "audioservice":
        return None
    try:
        name, channel = fields[1].strip(), fields[2].strip().upper()
        service_id, bitrate = int(fields[3], 16), int(fields[7])
        if not name or channel not in CHANNELS or bitrate < 0:
            return None
        return Service(name, channel, service_id, fields[8].strip(), bitrate)
    except ValueError:
        return None


def executable(value):
    """Resolve a binary path or PATH name, never a command with arguments."""
    path = shutil.which(value.strip())
    if not path:
        raise FileNotFoundError(
            f"DAB executable not found: {value}. Install dab-cmdline or select its executable."
        )
    return path


def playback_command(binary, channel, service):
    channel = channel.strip().upper()
    service = service.strip()
    if channel not in CHANNELS:
        raise ValueError("Choose a Band III channel, such as 11D or 12B.")
    if not service or "\x00" in service:
        raise ValueError("Enter the service name exactly as listed by the scanner.")
    return [executable(binary), "-M", "1", "-B", "BAND III", "-C", channel,
            "-P", service, "-Q"]


def scan_command(binary):
    # The scanner wraps around the whole band. -I skips transmitter ID lookup.
    return [executable(binary), "-B", "BAND III", "-C", "5A", "-Q", "-I", "1"]


class Decoder:
    """Manage one decoder process. Events are (kind, value) queue entries.

    Use start/stop on one controlling thread. Reader threads never call UI
    code. A stopped reader is joined before another process can start.
    """

    def __init__(self):
        self.process = None
        self.reader = None
        self.log_reader = None
        self.events = queue.Queue(maxsize=1000)
        self.cancelled = threading.Event()
        self.mode = None
        self.on_audio = None
        self.player_factory = AudioPlayer
        self.audio_rate = None
        self.volume = 50
        self.paused = False
        self.muted = False

    @property
    def running(self):
        return self.process is not None and self.process.poll() is None

    def emit(self, kind, value):
        # Never let slow consumers block pipe draining or shutdown.
        while True:
            try:
                self.events.put_nowait((kind, value))
                return
            except queue.Full:
                try:
                    self.events.get_nowait()
                except queue.Empty:
                    pass

    def start(self, command, mode="play"):
        self.stop()
        while not self.events.empty():
            self.events.get_nowait()
        self.cancelled.clear()
        self.mode = mode
        self.audio_rate = None
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        if mode == "audio":
            self.process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, **options)
            self.log_reader = threading.Thread(target=self.read_logs, args=(self.process,), daemon=True)
            self.log_reader.start()
            target = self.read_audio
        else:
            self.process = subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", **options,
            )
            target = self.read
        self.reader = threading.Thread(target=target, args=(self.process,), daemon=True)
        self.reader.start()

    def read_logs(self, process):
        with io.TextIOWrapper(process.stderr, encoding="utf-8", errors="replace") as logs:
            for line in logs:
                if line.rstrip():
                    self.emit("log", line.rstrip())

    def read_audio(self, process):
        import numpy as np
        player = None
        try:
            with process.stdout:
                while not self.cancelled.is_set():
                    frame = read_pcm_frame(process.stdout)
                    if frame is None:
                        break
                    rate, pcm = frame
                    audio = np.frombuffer(pcm, dtype="<i2").reshape(-1, 2).astype(np.float32) / 32768
                    if self.audio_rate != rate:
                        self.audio_rate = rate
                        self.emit("audio_ready", rate)
                    if self.on_audio and not self.paused:
                        self.on_audio(audio, rate)
                    if player is None:
                        player = self.player_factory()
                    gain = 0 if self.paused or self.muted else max(0, min(100, self.volume)) / 100
                    player.write(audio, rate, gain)
            code = process.wait()
            if self.log_reader:
                self.log_reader.join(timeout=3)
            if not self.cancelled.is_set():
                self.emit("exit", code)
        except Exception as error:
            if not self.cancelled.is_set():
                self.emit("error", str(error))
            if process.poll() is None:
                process.terminate()
        finally:
            if player:
                player.close()

    def read(self, process):
        try:
            with process.stdout:
                for line in process.stdout:
                    text = line.rstrip()
                    service = parse_service(text) if self.mode == "scan" else None
                    if service:
                        self.emit("service", service)
                    elif text:
                        self.emit("log", text)
            code = process.wait()
            if not self.cancelled.is_set():
                self.emit("exit", code)
        except (OSError, ValueError) as error:
            if not self.cancelled.is_set():
                self.emit("error", str(error))

    def stop(self):
        self.cancelled.set()
        process = self.process
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            if self.reader:
                self.reader.join(timeout=3)
                if self.reader.is_alive():
                    raise RuntimeError("DAB decoder output reader did not stop.")
            if self.log_reader:
                self.log_reader.join(timeout=3)
                if self.log_reader.is_alive():
                    raise RuntimeError("DAB diagnostics reader did not stop.")
        self.process = self.reader = None
        self.log_reader = None
        self.mode = None
        self.audio_rate = None


def main(argv=None):
    parser = argparse.ArgumentParser(description="DAB/DAB+ radio through dab-cmdline")
    parser.add_argument("channel", nargs="?", help="Band III block, e.g. 12B")
    parser.add_argument("service", nargs="?", help="Exact service name (quote spaces)")
    parser.add_argument("--scan", action="store_true", help="Scan all Band III channels")
    parser.add_argument("--decoder", default="airwaves-dab-rtlsdr")
    parser.add_argument("--scanner", default="dab-scanner-rtlsdr")
    parser.add_argument("--record", metavar="FILE", help="Record decoded audio to WAV or MP3")
    args = parser.parse_args(argv)
    decoder = Decoder()
    from .recording import Recording
    recording = Recording()
    try:
        if args.scan:
            if args.record:
                parser.error("Scanning does not produce audio to record")
            command = scan_command(args.scanner)
        else:
            if not args.channel or not args.service:
                parser.error("channel and service are required unless --scan is used")
            command = playback_command(args.decoder, args.channel, args.service)
        if args.record:
            if os.path.exists(args.record):
                raise FileExistsError("Recording file already exists. Choose a new filename.")
            recording.start(args.record)
            decoder.on_audio = recording.write
        decoder.start(command, "scan" if args.scan else "audio")
        while True:
            if not recording.errors.empty():
                raise OSError(recording.errors.get())
            try:
                kind, value = decoder.events.get(timeout=0.2)
            except queue.Empty:
                continue
            if kind == "exit":
                return value
            if kind == "error":
                print(value)
                return 1
            if kind == "service":
                print(f"{value.channel}: {value.name} ({value.codec}, {value.bitrate} kbps)")
            elif kind == "audio_ready":
                print(f"Decoded audio: {value} Hz")
            else:
                print(value)
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError) as error:
        print(error)
        return 1
    finally:
        try:
            decoder.stop()
        finally:
            recording.stop()


if __name__ == "__main__":
    raise SystemExit(main())
