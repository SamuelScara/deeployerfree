@echo off
REM Builds the Windows executable into dist\DeepLoyerFree.exe
cd /d "%~dp0"
uv run --with pyside6 --with pyinstaller pyinstaller --onefile --windowed --noconfirm --name DeepLoyerFree --icon deeployerfree.ico deeployerfree.py
if errorlevel 1 exit /b 1
echo Done: %cd%\dist\DeepLoyerFree.exe