#!/bin/sh
# 在 Linux 上用 Wine 打包 Windows 版 exe（不需要 Windows 電腦）
# 需要先安裝 Wine：sudo apt install wine
# 產出：dist/fastly-hosts-<版本>-windows-x64.zip
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$ROOT/.winbuild"                # 打包環境（Wine prefix + Windows 版 Python），重複使用
PY_VER="3.12.10"
export WINEPREFIX="$WORK/wineprefix" WINEDEBUG=-all WINEARCH=win64
PY="$WORK/pyroot/tools/python.exe"
VERSION=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$ROOT/fastly_hosts.py")

command -v wine >/dev/null || { echo "找不到 Wine，請先執行：sudo apt install wine"; exit 1; }
mkdir -p "$WORK"

if [ ! -f "$PY" ]; then
    echo "下載 Windows 版 Python $PY_VER（NuGet 免安裝版）…"
    wget -q -O "$WORK/python.nupkg" "https://api.nuget.org/v3-flatcontainer/python/$PY_VER/python.$PY_VER.nupkg"
    unzip -oq "$WORK/python.nupkg" 'tools/*' -d "$WORK/pyroot"
    wineboot -i >/dev/null 2>&1 || true
    wine "$PY" -m ensurepip --upgrade >/dev/null
    wine "$PY" -m pip install --no-warn-script-location pyinstaller
fi

echo "打包 fastly-hosts $VERSION …"
cd "$ROOT"
wine "$PY" -m PyInstaller --noconfirm --onefile --console --noupx \
    --name fastly-hosts --version-file "$ROOT/build/version_info.txt" \
    --workpath "$WORK/pyi-work" --specpath "$WORK" --distpath "$WORK/pyi-dist" \
    fastly_hosts.py > "$WORK/build.log" 2>&1 || { tail -20 "$WORK/build.log"; exit 1; }

mkdir -p "$ROOT/dist"
ZIP="$ROOT/dist/fastly-hosts-$VERSION-windows-x64.zip"
rm -f "$ZIP"
(cd "$WORK/pyi-dist" && zip -q -9 "$ZIP" fastly-hosts.exe)
echo "完成：$ZIP"
sha256sum "$WORK/pyi-dist/fastly-hosts.exe"
