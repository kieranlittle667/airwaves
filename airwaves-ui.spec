"""Desktop build. DAB binaries remain separately installed optional backends."""
import os
from PyInstaller.utils.hooks import collect_data_files

binaries = [(os.path.join(SPECPATH, "src", "airwaves", name), "airwaves")
            for name in ("libnrsc5.dll", "rtlsdr.dll")]
a = Analysis(
    [os.path.join(SPECPATH, "build", "gui_main.py")],
    pathex=[os.path.join(SPECPATH, "src")],
    binaries=binaries,
    datas=collect_data_files("airportsdata"),
    hiddenimports=["airwaves.sdr"],
)
packaged = {os.path.basename(name) for name, _, _ in a.binaries
            if os.path.dirname(name).endswith(".libs")}
a.binaries = [entry for entry in a.binaries
              if os.path.dirname(entry[0]) or entry[0] not in packaged]
exe = EXE(PYZ(a.pure), a.scripts, a.binaries, a.datas,
          name="airwaves-ui", console=False)
