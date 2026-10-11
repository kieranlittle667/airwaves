"""Native desktop controls. Receiver operations run on a single worker."""

import concurrent.futures
import queue
import sys
from pathlib import Path

from . import config, dab
from .recording import Recording


def bundled_decoder(name):
    """Find a portable backend beside the frozen app, falling back to PATH."""
    if getattr(sys, "frozen", False):
        path = Path(sys.executable).parent / "dab-backend" / (name + ".exe")
        if path.is_file():
            return str(path)
    return name

try:
    import wx
    from wx.lib.scrolledpanel import ScrolledPanel
except ImportError:
    wx = None


def main():
    if wx is None:
        print('Install the desktop extra first: uv sync --extra gui', file=sys.stderr)
        return 1
    app = wx.App(False)
    frame = RadioFrame()
    frame.Show()
    app.MainLoop()
    return 0


if wx is not None:
    class RadioFrame(wx.Frame):
        def __init__(self):
            super().__init__(None, title="Airwaves — radio receiver", size=(820, 650))
            self.SetMinSize((650, 480))
            self.worker = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            self.pending = None
            self.closing = False
            self.receiver = None
            self.sdr = None
            self.devices = []
            self.decoder = dab.Decoder()
            self.recording = Recording()
            self.decoder.on_audio = self.recording.write
            self.services = []
            self.settings = config.load()
            self.controls = []
            panel = wx.Panel(self)
            layout = wx.BoxSizer(wx.VERTICAL)
            title = wx.StaticText(panel, label="Airwaves")
            title.SetFont(title.GetFont().Bold().Larger().Larger())
            layout.Add(title, 0, wx.ALL, 12)
            self.pages = wx.Notebook(panel)
            self.analog_page = ScrolledPanel(self.pages)
            self.dab_page = ScrolledPanel(self.pages)
            self.pages.AddPage(self.analog_page, "AM / FM / shortwave / aviation / HD")
            self.pages.AddPage(self.dab_page, "DAB / DAB+")
            self.build_analog()
            self.build_dab()
            layout.Add(self.pages, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
            recording_row = wx.BoxSizer(wx.HORIZONTAL)
            for label, callback in [("Start &recording…", self.start_recording),
                                    ("Stop recording", self.stop_recording)]:
                button = wx.Button(panel, label=label)
                button.Bind(wx.EVT_BUTTON, callback)
                self.controls.append(button)
                recording_row.Add(button, 1, wx.RIGHT, 6)
            layout.Add(recording_row, 0, wx.ALL | wx.EXPAND, 12)
            layout.Add(wx.StaticText(panel, label="Recording status"), 0, wx.LEFT | wx.RIGHT, 12)
            self.recording_status = wx.TextCtrl(panel, value="Not recording", style=wx.TE_READONLY)
            self.recording_status.SetName("Recording status")
            layout.Add(self.recording_status, 0, wx.LEFT | wx.RIGHT | wx.EXPAND, 12)
            self.stop_button = wx.Button(panel, label="&Stop receiver / cancel DAB scan")
            self.stop_button.Bind(wx.EVT_BUTTON, lambda e: self.submit(self.stop_all, "Stopped"))
            self.controls.append(self.stop_button)
            layout.Add(self.stop_button, 0, wx.ALL | wx.EXPAND, 12)
            layout.Add(wx.StaticText(panel, label="Receiver status"), 0, wx.LEFT | wx.RIGHT, 12)
            self.status = wx.TextCtrl(panel, value="Ready. Choose a device or configure a DAB decoder.",
                                      style=wx.TE_READONLY)
            self.status.SetName("Receiver status")
            layout.Add(self.status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
            panel.SetSizer(layout)
            self.timer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, self.tick, self.timer)
            self.timer.Start(200)
            self.Bind(wx.EVT_CLOSE, self.close)
            wx.CallAfter(self.frequency.SetFocus)

        def field(self, parent, sizer, label, create_control):
            row = wx.BoxSizer(wx.HORIZONTAL)
            # MSAA associates native edits with preceding static labels. Creation
            # order matters even when the sizer displays the label first.
            row.Add(wx.StaticText(parent, label=label), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
            control = create_control()
            control.SetName(label.replace("&", ""))
            row.Add(control, 1, wx.EXPAND)
            sizer.Add(row, 0, wx.EXPAND | wx.ALL, 6)
            self.controls.append(control)
            return control

        def buttons(self, parent, sizer, items):
            row = wx.BoxSizer(wx.HORIZONTAL)
            for label, callback in items:
                button = wx.Button(parent, label=label)
                button.Bind(wx.EVT_BUTTON, callback)
                self.controls.append(button)
                row.Add(button, 1, wx.RIGHT, 6)
            sizer.Add(row, 0, wx.EXPAND | wx.ALL, 6)

        def build_analog(self):
            p = self.analog_page
            s = wx.BoxSizer(wx.VERTICAL)
            self.device = self.field(p, s, "RTL-SDR &device", lambda: wx.Choice(p))
            self.buttons(p, s, [("&Refresh devices", self.refresh_devices)])
            self.region = self.field(p, s, "&Region", lambda: wx.Choice(p, choices=["Europe", "US"]))
            self.region.SetSelection(0)
            self.frequency = self.field(p, s, "&Frequency (MHz)", lambda: wx.TextCtrl(p, value="87.5", style=wx.TE_PROCESS_ENTER))
            self.frequency.Bind(wx.EVT_TEXT_ENTER, self.tune)
            self.buttons(p, s, [("&Listen / tune", self.tune),
                               ("Seek &previous", lambda e: self.seek(-1)),
                               ("Seek &next", lambda e: self.seek(1))])
            self.volume = self.field(p, s, "&Volume (0–100)", lambda: wx.SpinCtrl(p, min=0, max=100, initial=50))
            self.volume.Bind(wx.EVT_SPINCTRL, self.change_volume)
            self.volume.Bind(wx.EVT_TEXT, self.change_volume)
            row = wx.BoxSizer(wx.HORIZONTAL)
            self.pause = wx.CheckBox(p, label="&Pause")
            self.mute = wx.CheckBox(p, label="&Mute")
            for control in (self.pause, self.mute):
                control.Bind(wx.EVT_CHECKBOX, self.change_audio)
                self.controls.append(control)
                row.Add(control, 0, wx.ALL, 6)
            s.Add(row)
            self.buttons(p, s, [("Start &HD Radio", lambda e: self.receiver_action("hd_start")),
                               ("Return to &analog", lambda e: self.receiver_action("hd_stop"))])
            self.hd = self.field(p, s, "HD &service", lambda: wx.Choice(p))
            self.hd.Bind(wx.EVT_CHOICE, self.select_hd)
            self.hd_numbers = []
            self.presets = self.field(p, s, "Saved &presets", lambda: wx.Choice(p))
            self.reload_presets()
            self.buttons(p, s, [("Save &preset", self.save_preset), ("Listen to selected preset", self.load_preset)])
            self.metadata = self.field(p, s, "Station / radio text / signal", lambda: wx.TextCtrl(p, style=wx.TE_READONLY | wx.TE_MULTILINE))
            s.Add(wx.StaticText(p, label="Enter AM in MHz: 1.4 means 1400 kHz. HD Radio requires an FM station."),
                  0, wx.ALL, 6)
            p.SetSizer(s)
            p.SetupScrolling(scroll_x=False)

        def build_dab(self):
            p = self.dab_page
            s = wx.BoxSizer(wx.VERTICAL)
            s.Add(wx.StaticText(p, label="DAB/DAB+ uses a separate dab-cmdline decoder and the first RTL-SDR dongle.\n"
                               "Install the Airwaves DAB backend; see docs/dab-windows.md. Volume controls are on the first tab."),
                  0, wx.ALL, 6)
            self.dab_binary = self.field(p, s, "Playback &decoder", lambda: wx.TextCtrl(p, value=self.settings.get("dab_decoder", bundled_decoder("airwaves-dab-rtlsdr"))))
            self.scanner_binary = self.field(p, s, "DAB &scanner", lambda: wx.TextCtrl(p, value=self.settings.get("dab_scanner", bundled_decoder("dab-scanner-rtlsdr"))))
            self.buttons(p, s, [("Browse decoder", lambda e: self.browse(self.dab_binary)),
                               ("Browse scanner", lambda e: self.browse(self.scanner_binary))])
            self.channel = self.field(p, s, "Band III &channel", lambda: wx.Choice(p, choices=list(dab.CHANNELS)))
            self.channel.SetStringSelection("12B")
            self.service = self.field(p, s, "&Service name (case sensitive)", lambda: wx.TextCtrl(p))
            self.buttons(p, s, [("Scan &Band III", self.scan_dab), ("&Play DAB / DAB+", self.play_dab)])
            self.station_list = self.field(p, s, "Discovered &stations", lambda: wx.ListBox(p))
            self.station_list.Bind(wx.EVT_LISTBOX, self.choose_service)
            self.station_list.Bind(wx.EVT_LISTBOX_DCLICK, self.play_dab)
            s.Add(wx.StaticText(p, label="Scanning may take several minutes. Stations can appear in batches.\n"
                               "Select a result, then press Play. Stop cancels scanning or playback."), 0, wx.ALL, 6)
            s.Add(wx.StaticText(p, label="DAB decoder diagnostics"), 0, wx.LEFT | wx.RIGHT, 6)
            self.log = wx.TextCtrl(p, style=wx.TE_MULTILINE | wx.TE_READONLY)
            self.log.SetName("DAB decoder diagnostics")
            s.Add(self.log, 1, wx.ALL | wx.EXPAND, 6)
            p.SetSizer(s)
            p.SetupScrolling(scroll_x=False)

        def submit(self, function, success="Ready", done=None):
            if self.pending or self.closing:
                return
            for control in self.controls:
                control.Disable()
            self.status.ChangeValue("Working…")
            self.pending = (self.worker.submit(function), success, done)

        def refresh_devices(self, event=None):
            def discover():
                from . import sdr
                self.sdr = sdr
                return sdr.list_devices()
            def done(devices):
                self.devices = devices
                self.device.Set([f"{d.index}: {d.name} ({d.serial})" for d in devices])
                if devices:
                    self.device.SetSelection(0)
                else:
                    self.status.ChangeValue("No RTL-SDR dongle found. Connect a dongle with its USB driver installed.")
            self.submit(discover, "Device list refreshed", done)

        def tune(self, event=None, hd_program=None):
            try:
                frequency = float(self.frequency.GetValue())
                device = self.devices[self.device.GetSelection()] if self.device.GetSelection() >= 0 else None
                region = "eu" if self.region.GetSelection() == 0 else "us"
                volume, paused, muted = self.volume.GetValue(), self.pause.GetValue(), self.mute.GetValue()
                if not device:
                    raise ValueError("Refresh devices and select an RTL-SDR dongle first.")
            except ValueError as error:
                self.show_error(error)
                return
            def listen():
                # Validate before opening hardware (Receiver.__init__ opens USB).
                if self.sdr.band_for(frequency, self.sdr.REGIONS[region]) is None:
                    raise ValueError("Frequency is outside the supported bands for this region.")
                self.recording.stop()
                self.decoder.stop()
                if self.receiver and (self.receiver.device_index != device.index or self.receiver.bands != self.sdr.REGIONS[region]):
                    self.stop_analog()
                if self.receiver:
                    self.receiver.tune(frequency)
                else:
                    self.receiver = self.sdr.Receiver(device.index, frequency, region=region)
                    self.receiver.on_audio = lambda audio: self.recording.write(audio, self.sdr.AUDIO_RATE)
                    self.receiver.start()
                self.receiver.volume = volume
                self.receiver.paused = paused
                self.receiver.muted = muted
                if hd_program is not None:
                    self.receiver.hd_start()
                    self.receiver.select_hd_program(hd_program)
                if self.receiver.error:
                    raise self.receiver.error
            self.submit(listen, "Listening")

        def seek(self, direction):
            def seek_station():
                if not self.receiver:
                    raise ValueError("Start the analog receiver first.")
                self.recording.stop()
                return self.receiver.seek(direction)
            def done(frequency):
                if frequency is None:
                    self.status.ChangeValue("No other station found in this band.")
                else:
                    self.frequency.ChangeValue(str(frequency))
            self.submit(seek_station, "Listening", done)

        def receiver_action(self, method):
            def action():
                if not self.receiver:
                    raise ValueError("Start the analog receiver first.")
                if method == "hd_start" and self.receiver.band != self.sdr.FM:
                    raise ValueError("HD Radio is available on FM only.")
                self.recording.stop()
                getattr(self.receiver, method)()
            self.submit(action, "Receiver updated")

        def change_volume(self, event):
            self.decoder.volume = self.volume.GetValue()
            if self.receiver:
                self.receiver.volume = self.volume.GetValue()

        def change_audio(self, event):
            self.decoder.paused = self.pause.GetValue()
            self.decoder.muted = self.mute.GetValue()
            if self.receiver:
                self.receiver.paused = self.pause.GetValue()
                self.receiver.muted = self.mute.GetValue()

        def select_hd(self, event):
            if self.receiver and self.hd.GetSelection() >= 0:
                number = self.hd_numbers[self.hd.GetSelection()]
                def select():
                    self.recording.stop()
                    self.receiver.select_hd_program(number)
                self.submit(select, "HD service selected")

        def start_recording(self, event):
            if self.recording.active:
                self.show_error(ValueError("A recording is already running. Stop it before choosing a new file."))
                return
            if not self.receiver and not (self.decoder.running and self.decoder.mode == "audio"):
                self.show_error(ValueError("Start listening to a station before recording. A DAB scan has no audio."))
                return
            with wx.FileDialog(self, "Save radio recording", defaultFile="radio.wav",
                               wildcard="WAV audio (*.wav)|*.wav|MP3 audio (*.mp3)|*.mp3",
                               style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
                if dialog.ShowModal() != wx.ID_OK:
                    return
                path = dialog.GetPath()
                from pathlib import Path
                if not Path(path).suffix:
                    path += ".mp3" if dialog.GetFilterIndex() == 1 else ".wav"
                    if Path(path).exists() and wx.MessageBox(
                        f"Replace {path}?", "Recording file exists", wx.YES_NO | wx.NO_DEFAULT, self
                    ) != wx.YES:
                        return
            rate = self.sdr.AUDIO_RATE if self.receiver else self.decoder.audio_rate
            self.submit(lambda: self.recording.start(path, rate), "Recording started")

        def stop_recording(self, event):
            self.submit(self.recording.stop, "Recording saved")

        def reload_presets(self):
            self.preset_items = list(config.presets().items())
            self.presets.Set([f"{number}: {text}" for number, text in self.preset_items])
            if self.preset_items:
                self.presets.SetSelection(0)

        def save_preset(self, event):
            try:
                if not self.receiver:
                    raise ValueError("Start listening before saving a preset.")
                text = self.sdr.Preset(self.receiver.freq_mhz, self.receiver.hd_program).text()
                config.save(str(config.next_preset_number()), text, config.PRESETS)
                self.reload_presets()
                self.status.ChangeValue("Preset saved")
            except (OSError, ValueError) as error:
                self.show_error(error)

        def load_preset(self, event):
            index = self.presets.GetSelection()
            if index >= 0:
                # Loading sdr here also validates the existing CLI preset format.
                try:
                    from . import sdr
                    preset = sdr.Preset.parse(self.preset_items[index][1])
                    if preset is None:
                        raise ValueError("This preset is not a valid frequency or HD service.")
                    self.frequency.ChangeValue(str(preset.freq_mhz))
                    self.tune(hd_program=preset.hd_program)
                except (OSError, ValueError, ImportError) as error:
                    self.show_error(error)

        def browse(self, control):
            with wx.FileDialog(self, "Select DAB executable", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
                if dialog.ShowModal() == wx.ID_OK:
                    control.ChangeValue(dialog.GetPath())

        def save_dab_settings(self):
            config.save("dab_decoder", self.dab_binary.GetValue())
            config.save("dab_scanner", self.scanner_binary.GetValue())

        def play_dab(self, event=None):
            try:
                command = dab.playback_command(self.dab_binary.GetValue(), self.channel.GetStringSelection(), self.service.GetValue())
                self.save_dab_settings()
            except (OSError, ValueError) as error:
                self.show_error(error)
                return
            def play():
                self.stop_analog()
                self.recording.stop()
                self.decoder.start(command, "audio")
            self.submit(play, "DAB decoder started; waiting for decoded audio.")

        def scan_dab(self, event):
            try:
                command = dab.scan_command(self.scanner_binary.GetValue())
                self.save_dab_settings()
            except (OSError, ValueError) as error:
                self.show_error(error)
                return
            self.services.clear()
            self.station_list.Clear()
            self.log.Clear()
            def scan():
                self.stop_analog()
                self.recording.stop()
                self.decoder.start(command, "scan")
            self.submit(scan, "Scanning Band III… Stop cancels. Results may arrive in batches.")

        def choose_service(self, event):
            index = self.station_list.GetSelection()
            if index >= 0:
                service = self.services[index]
                self.channel.SetStringSelection(service.channel)
                self.service.ChangeValue(service.name)

        def stop_analog(self):
            if self.receiver:
                self.recording.stop()
                self.receiver.on_audio = None
                self.receiver.stop()
                self.receiver = None

        def stop_all(self):
            try:
                self.stop_analog()
            finally:
                try:
                    self.decoder.stop()
                finally:
                    self.recording.stop()

        def show_error(self, error):
            self.status.ChangeValue(str(error))
            wx.MessageBox(str(error), "Airwaves", wx.OK | wx.ICON_ERROR, self)

        def tick(self, event):
            # All widgets are updated on this UI thread, including recorder errors.
            if not self.recording.errors.empty() and not self.pending:
                error = self.recording.errors.get()
                self.submit(self.recording.stop, f"Recording stopped: {error}")
            if self.pending:
                future, success, done = self.pending
                if future.done():
                    self.pending = None
                    if self.closing and done != self.finish_close:
                        # A running operation completed. Stop any receiver it opened.
                        self.pending = (self.worker.submit(self.stop_all), "", self.finish_close)
                        return
                    if not self.closing:
                        for control in self.controls:
                            control.Enable()
                    try:
                        value = future.result()
                        self.status.ChangeValue(success)
                        if done:
                            done(value)
                            if done == self.finish_close:
                                return
                    except Exception as error:
                        self.show_error(error)
            while True:
                try:
                    kind, value = self.decoder.events.get_nowait()
                except queue.Empty:
                    break
                if kind == "service" and value not in self.services:
                    self.services.append(value)
                    self.station_list.Append(f"{value.channel}: {value.name} — {value.codec}, {value.bitrate} kbps")
                elif kind in ("log", "error"):
                    if self.log.GetLastPosition() > 30000:
                        self.log.Remove(0, 15000)
                    self.log.AppendText(str(value) + "\n")
                    if kind == "error":
                        self.status.ChangeValue(str(value))
                        if self.recording.active and not self.pending:
                            self.submit(self.recording.stop, f"Recording saved; DAB stopped: {value}")
                elif kind == "exit":
                    if self.recording.active and not self.pending:
                        self.submit(self.recording.stop, "Recording saved; DAB decoder exited.")
                    if value:
                        self.status.ChangeValue(f"DAB decoder exited (code {value}). Read the diagnostics for details.")
                    elif self.decoder.mode == "scan":
                        self.status.ChangeValue(f"Scan complete: {len(self.services)} stations found.")
                    else:
                        self.status.ChangeValue("DAB decoder stopped. Check diagnostics if playback did not start.")
                elif kind == "audio_ready":
                    self.status.ChangeValue(f"Receiving DAB audio at {value} Hz")
            description = self.recording.describe()
            if description != self.recording_status.GetValue():
                self.recording_status.ChangeValue(description)
            receiver = self.receiver
            if receiver and not self.pending:
                programs = dict(receiver.hd_programs)
                labels = [f"HD{n + 1}: {name}" for n, name in sorted(programs.items())]
                if labels != list(self.hd.GetItems()):
                    self.hd_numbers = sorted(programs)
                    self.hd.Set(labels)
                if receiver.hd_program in self.hd_numbers:
                    self.hd.SetSelection(self.hd_numbers.index(receiver.hd_program))
                digital = " | HD locked" if receiver.hd_locked else " | Waiting for HD" if receiver.hd_active else ""
                text = f"{receiver.freq_mhz:g} MHz | {receiver.signal_db} dB | {'Stereo' if receiver.stereo else 'Mono'}{digital}\n{receiver.rds_name}\n{receiver.rds_text}"
                if receiver.alert:
                    text += "\n" + receiver.alert.describe()
                if text != self.metadata.GetValue():
                    self.metadata.ChangeValue(text)
                if receiver.error:
                    error = receiver.error
                    self.submit(self.stop_analog, f"Receiver stopped: {error}")

        def close(self, event):
            if event.CanVeto():
                event.Veto()
            if self.closing:
                return
            if self.pending:
                self.closing = True
                self.status.ChangeValue("Closing after the current receiver operation…")
            else:
                self.submit(self.stop_all, "", self.finish_close)
                self.closing = True
            for control in self.controls:
                control.Disable()

        def finish_close(self, value=None):
            self.timer.Stop()
            self.worker.shutdown(wait=False)
            self.Destroy()


if __name__ == "__main__":
    raise SystemExit(main())
