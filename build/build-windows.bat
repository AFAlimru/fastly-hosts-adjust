@echo off
rem 在 Windows 上打包 exe（需要先安裝 Python 3.8 以上，安裝時勾選 Add python.exe to PATH）
rem 產出：dist\fastly-hosts.exe
cd /d "%~dp0.."
python -m pip install pyinstaller
if errorlevel 1 (echo 安裝 PyInstaller 失敗 & pause & exit /b 1)
python -m PyInstaller --noconfirm --onefile --console --noupx --name fastly-hosts ^
    --version-file "%CD%\build\version_info.txt" --workpath build\pyi-work --specpath build\pyi-work ^
    --distpath dist fastly_hosts.py
if errorlevel 1 (echo 打包失敗 & pause & exit /b 1)
echo.
echo 完成：dist\fastly-hosts.exe
pause
