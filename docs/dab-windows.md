# DAB/DAB+ on Windows

The Airwaves PCM backend is built from the pinned GPL dab-cmdline decoder,
with a small adapter that preserves each audio block's sample rate. Both
DAB (MP2) and DAB+ (AAC) are decoded automatically. No AAC codec installation
is needed when using the portable backend package.

1. Install the RTL-SDR's WinUSB driver using Zadig, as described in the main
   README. Select the dongle's Interface 0, checking its USB identity before
   changing its driver.
2. Download the portable desktop ZIP from the
   [fork's releases](https://github.com/kieranlittle667/airwaves/releases).
   Extract the entire ZIP; Airwaves finds the included `dab-backend` folder
   automatically. Alternatively, download the `airwaves-dab-windows` artifact from a **successful**
   [DAB Windows backend workflow](https://github.com/kieranlittle667/airwaves/actions/workflows/dab-windows.yml).
   Extract the entire ZIP into a folder; keep its DLLs alongside the executables.
3. Open Airwaves' DAB tab. If using the separate backend artifact, select
   `airwaves-dab-rtlsdr.exe` as the playback decoder and
   `dab-scanner-rtlsdr.exe` as the scanner.
4. Connect the dongle and an antenna covering Band III (roughly 174–240 MHz).
   Scan Band III, choose a station, and press Play.

The backend currently uses the first RTL-SDR dongle. DAB scanning stops
audio and any recording. Close other SDR applications before listening;
two programs cannot open the same dongle simultaneously.

The build must succeed before this artifact is available. An ordinary Qt-DAB
or welle.io GUI installer is a separate receiver and does not provide the
Airwaves framed PCM protocol. It can be used independently to check signal
reception, but cannot be selected as this app's playback decoder.

The portable package includes the modified decoder source and the adaptation
script. To reproduce the Windows build, use the packages and commands in
`.github/workflows/dab-windows.yml`. This is a development backend; reception
still needs verification with real hardware.
