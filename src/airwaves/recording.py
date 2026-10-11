"""A recording session shared by the desktop receiver modes."""
import queue
import threading
from pathlib import Path

from .recorder import Recorder


class Recording:
    """Record decoded stereo audio at its actual rate, before playback volume.

    DAB sessions wait for the first audio block to learn its sample rate.
    Stop detaches the writer atomically, then flushes outside the callback lock.
    """

    def __init__(self):
        self.lock = threading.RLock()
        self.writer = None
        self.path = None
        self.rate = None
        self.frames = 0
        self.errors = queue.SimpleQueue()

    @property
    def active(self):
        return self.path is not None

    def start(self, path, rate=None):
        if Path(path).suffix.lower() not in (".wav", ".mp3"):
            raise ValueError("Choose a .wav or .mp3 recording file.")
        self.stop()
        # Verify the destination before arming a DAB session. The file dialog
        # confirms any replacement; a no-signal DAB recording stays empty.
        with open(path, "wb"):
            pass
        with self.lock:
            self.path = str(path)
            self.rate = rate
            self.frames = 0
            if rate is not None:
                try:
                    self.open_writer(rate)
                except Exception:
                    self.path = None
                    raise

    def open_writer(self, rate):
        self.writer = Recorder(self.path, rate, mp3=Path(self.path).suffix.lower() == ".mp3")
        self.writer.on_error = self.errors.put
        self.rate = rate

    def write(self, audio, rate):
        with self.lock:
            if not self.path:
                return
            try:
                if self.writer is None:
                    self.open_writer(rate)
                if self.rate != rate:
                    raise ValueError("The station's sample rate changed. Start a new recording.")
                self.writer.write(audio.copy())
                self.frames += len(audio)
            except Exception as error:
                self.errors.put(error)
                # The UI will detach and flush the writer via stop().
                self.path = None

    def stop(self):
        with self.lock:
            writer, self.writer = self.writer, None
            self.path = None
        if writer:
            writer.close()

    def describe(self):
        with self.lock:
            if not self.path:
                return "Not recording"
            if self.writer is None:
                return f"Waiting for decoded audio: {self.path}"
            return f"Recording: {self.frames / self.rate:.1f} seconds — {self.path}"
