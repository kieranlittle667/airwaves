"""Adapt pinned dab-cmdline example 3 to Airwaves' framed PCM protocol.

Run against a fresh checkout at DAB_COMMIT. Retains upstream GPL notices.
Native builds use MSYS2/MinGW on Windows or standard CMake on Linux.
"""
import pathlib
import re
import subprocess
import sys

DAB_COMMIT = "8b8230526a68d9ec52911dae0bd455cf1bb2fbad"

PCM_OUTPUT = r'''
    // Airwaves protocol: AWPC, sample rate (u32 LE), byte count (u32 LE),
    // followed by interleaved stereo signed 16-bit little-endian PCM.
    // The library duplicates mono channels; isStereo describes the broadcast.
    const uint32_t count = static_cast<uint32_t>(size) * 2;
    unsigned char header[12] = {'A', 'W', 'P', 'C'};
    for (int i = 0; i < 4; ++i) {
        header[4 + i] = (static_cast<uint32_t>(rate) >> (8 * i)) & 0xff;
        header[8 + i] = (count >> (8 * i)) & 0xff;
    }
    fwrite(header, 1, sizeof(header), stdout);
    fwrite(buffer, 1, count, stdout);
    fflush(stdout);
'''


def prepare(root):
    root = pathlib.Path(root)
    commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if commit != DAB_COMMIT:
        raise ValueError(f"Expected dab-cmdline commit {DAB_COMMIT}, got {commit}")
    for folder in ("example-3", "dab-scanner"):
        path = root / folder / "CMakeLists.txt"
        text = path.read_text()
        text = text.replace(" -fsanitize=address", "").replace("-municode", "")
        text = text.replace("find_library (PTHREADS pthread)", "find_library (PTHREADS NAMES pthread winpthread)")
        text = text.replace("dab-rtlsdr-3", "airwaves-dab-rtlsdr")
        text += "\nif(WIN32)\n  add_compile_definitions(NOMINMAX)\nendif()\n"
        path.write_text(text)
    path = root / "devices" / "rtlsdr-handler" / "rtlsdr-handler.h"
    text = path.read_text().replace("#include\t<dlfcn.h>",
                                   "#ifdef _WIN32\n#include <windows.h>\n#else\n#include <dlfcn.h>\n#endif")
    text = text.replace("typedef\tvoid *HINSTANCE;", "#ifndef _WIN32\ntypedef void *HINSTANCE;\n#endif")
    path.write_text(text)
    path = root / "devices" / "rtlsdr-handler" / "rtlsdr-handler.cpp"
    text = path.read_text().replace('LoadLibrary ((wchar_t *)L"rtlsdr.dll")', 'LoadLibraryW(L"rtlsdr.dll")')
    path.write_text(text)
        path = root / folder / "main.cpp"
        text = path.read_text()
        text = text.replace("struct sigaction sigact;", "")
        text = re.sub(r"\s*sigact.sa_handler = sighandler;\s*sigemptyset\(&sigact.sa_mask\);\s*sigact.sa_flags = 0;",
                      "\n\tsignal(SIGINT, sighandler);\n\tsignal(SIGTERM, sighandler);", text)
        if folder == "example-3":
            if "fwrite ((void *)buffer, size, 2, stdout);" not in text:
                raise ValueError("Upstream PCM callback changed or has already been patched")
            text = text.replace("fwrite ((void *)buffer, size, 2, stdout);", PCM_OUTPUT)
            text = "#ifdef _WIN32\n#include <io.h>\n#include <fcntl.h>\n#endif\n" + text
            text = text.replace("int\tmain (int argc, char **argv) {",
                                "int\tmain (int argc, char **argv) {\n#ifdef _WIN32\n_setmode(_fileno(stdout), _O_BINARY);\n#endif")
        path.write_text(text)


if __name__ == "__main__":
    prepare(sys.argv[1])
