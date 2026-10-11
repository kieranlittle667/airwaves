@echo off
rem Builds dist\airwaves-ui.exe with native wxPython controls.
setlocal
cd /d "%~dp0"
uv sync --extra gui || exit /b 1
if not exist build mkdir build
echo from airwaves.gui import main> build\gui_main.py
echo raise SystemExit(main())>> build\gui_main.py
uv run --with pyinstaller pyinstaller --noconfirm --clean --workpath build\pyinstaller-ui --distpath dist airwaves-ui.spec || exit /b 1
echo Built dist\airwaves-ui.exe
