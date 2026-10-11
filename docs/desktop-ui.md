# Airwaves desktop UI and DAB/DAB+

For Windows, download the portable ZIP from the
[fork's releases](https://github.com/kieranlittle667/airwaves/releases),
extract it, and open `airwaves-ui.exe`. Keep the `dab-backend` folder beside
the application so its decoder paths are filled automatically.

Install Python 3.10 or later and uv, then run:

```console
uv sync --extra gui
uv run airwaves-ui
```

wxPython supplies native controls, named inputs, standard focus traversal,
and Alt access keys. Tab between controls, use arrows in station lists, and
press Enter in the frequency box to tune. The read-only status and metadata
fields can be focused and read with a screen reader. Speech announcements
are not forced on every signal update. NVDA/JAWS behaviour still needs user
testing; this implementation does not claim an accessibility certification.

On Windows, `build-ui.bat` produces `dist/airwaves-ui.exe` without needing
Python on the receiving computer. The existing `build.bat` still builds
the console receiver. On Linux, install wxPython's native prerequisites
using your distribution's instructions if pip cannot find a suitable wheel.

## Analog and HD Radio

Connect an RTL-SDR with the driver described in the main README, press
Refresh devices, and select it. Choose Europe or US, enter the frequency
in MHz, and press Listen. Seek previous/next scans the current band.
Pause, mute, volume, station text, signal strength, HD service selection,
and saved analog/HD presets use the existing Receiver API. Presets share
the existing CLI's `airwaves.conf` format.

The UI covers local listening and WAV/MP3 recording. Casting and ACARS
remain available through the existing `sdr` CLI.

## Recording every audio mode

Start listening, then press Start recording and select a `.wav` or `.mp3`
file. Recording supports AM, FM, shortwave, aviation, NOAA weather, HD
Radio, DAB and DAB+. Press Stop recording to finish the file while continuing
to listen. Stopping the receiver, changing frequency or digital service,
seeking, starting a DAB scan, or closing the window also finalizes the file.
This avoids mixing different stations into one recording.

Audio is recorded before playback volume and mute; muting the speaker keeps
recording. Pause pauses both listening and recording. DAB starts recording
when decoded audio first arrives, using the station's actual sample rate.
Its playback is converted to 48 kHz independently. If a station changes its
sample rate during recording, recording stops with an error rather than
writing audio at the wrong speed. If no DAB audio ever arrives, the selected
file remains empty. Recording status shows elapsed captured audio and the
destination. MP3 uses the existing 320 kbps encoder. WAV stores stereo 16-bit
PCM. Disk-write errors are reported without stopping radio playback.

Only the selected station's decoded audio is captured, not other apps or
system sounds. Scans have no audio. ACARS messages are text and can be saved
using the CLI's `--log` option.

## Optional DAB and DAB+ decoder

DAB uses a different demodulator from FM/HD Radio. The adapter launches
[JvanKatwijk/dab-cmdline](https://github.com/JvanKatwijk/dab-cmdline) as a
separate process. The Airwaves adaptation of example 3 decodes DAB (MP2)
and DAB+ (AAC), and sends framed PCM with sample-rate information to Python
for playback and recording. Install `airwaves-dab-rtlsdr` and optionally
`dab-scanner-rtlsdr`. For Windows, see the
[portable backend installation](dab-windows.md). The native backends are
separate from the desktop executable. Qt-DAB, welle-cli, and unmodified
dab-cmdline examples have different interfaces and cannot be selected as
replacement executables for this adapter.

The command contract was checked against upstream commit
`8b8230526a68d9ec52911dae0bd455cf1bb2fbad`. See its README for native
dependency installation. For example, after installing those dependencies
on Linux:

```sh
git clone https://github.com/JvanKatwijk/dab-cmdline.git
cd dab-cmdline
git checkout 8b8230526a68d9ec52911dae0bd455cf1bb2fbad
# From an Airwaves checkout, run its adapter script against this folder:
python /path/to/airwaves/scripts/prepare_dab.py .
cmake -S example-3 -B build-player -DRTLSDR=ON -DDEBUG_PRINT_TO_STDERR=ON
cmake --build build-player
cmake -S dab-scanner -B build-scanner -DRTLSDR=ON
cmake --build build-scanner
```

Select the resulting binaries in Airwaves or add their directories to PATH.
The Windows workflow builds the adapted decoder and scanner with their
required DLLs. Live reception still needs verification with hardware.

In the DAB tab, set both executable paths, then Scan Band III. The scanner
checks the whole band, which may take several minutes, and output buffering
can delay results. Choose a station to fill its block and exact service name,
then press Play DAB / DAB+. You can also enter a known block and service name
without scanning. Service names are case sensitive. DAB+ is selected by the
broadcast service automatically; no separate DAB+ switch is needed.

The decoder selects the first RTL-SDR dongle; the analog device selector does
not control it. Disconnect extra dongles to avoid ambiguity. Starting DAB or
a DAB scan stops the analog receiver and releases USB first. Starting analog
stops DAB first. Stop cancels either mode; closing the window cleans up its
decoder process and finalizes recording. Pause/mute/volume on the first tab
also control DAB playback. DAB casting, slideshow, and signal metadata are
not integrated.

The DAB diagnostics box contains decoder messages, including missing devices,
weak reception, and missing services. Starting a process is not proof of
successful reception. A Band III antenna and sufficient local signal are
required. Live DAB/DAB+ and analog audio have not been verified without
connected radio hardware.

The same backend is available from the command line:

```console
uv run dab --scan --scanner /path/to/dab-scanner-rtlsdr
uv run dab 12B "BBC Radio 4" --decoder /path/to/airwaves-dab-rtlsdr
uv run dab 12B "BBC Radio 4" --record radio.wav
```

Stop with Ctrl+C. These launch the real native decoder, not internet streams.
