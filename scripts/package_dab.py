"""Copy only the MinGW DLL dependencies of the native backend executables."""
import pathlib
import re
import shutil
import subprocess
import sys


def package(destination, bin_dir):
    destination, bin_dir = pathlib.Path(destination), pathlib.Path(bin_dir)
    available = {p.name.lower(): p for p in bin_dir.glob("*.dll")}
    rtl = available.get("librtlsdr.dll") or available.get("rtlsdr.dll")
    if rtl is None:
        raise FileNotFoundError("RTL-SDR runtime DLL is missing")
    shutil.copy2(rtl, destination / "rtlsdr.dll")
    pending = list(destination.glob("*.exe")) + [destination / "rtlsdr.dll"]
    seen = set()
    while pending:
        path = pending.pop()
        if path.name.lower() in seen:
            continue
        seen.add(path.name.lower())
        output = subprocess.check_output(["objdump", "-p", str(path)], text=True)
        for name in re.findall(r"DLL Name:\s*(\S+)", output):
            source = available.get(name.lower())
            if source:
                target = destination / source.name
                if not target.exists():
                    shutil.copy2(source, target)
                pending.append(target)
    licenses = bin_dir.parent / "share" / "licenses"
    if licenses.is_dir():
        shutil.copytree(licenses, destination / "runtime-licenses", dirs_exist_ok=True)
    packages = subprocess.check_output(["pacman", "-Q"], text=True)
    (destination / "runtime-packages.txt").write_text(
        "Build dependencies and versions (MSYS2 UCRT64):\n" + packages +
        "\nRuntime source packages and build recipes:\n"
        "https://repo.msys2.org/mingw/sources/\n"
        "https://github.com/msys2/MINGW-packages\n", encoding="utf-8")


if __name__ == "__main__":
    package(*sys.argv[1:])
