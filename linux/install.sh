#!/bin/sh
# 建立 fastly-hosts 的捷徑：應用程式選單 + 桌面圖示，之後雙擊就能開啟選單。
# 用法：sh linux/install.sh        移除：sh linux/install.sh --remove
set -e

APP_ID="fastly-hosts"
SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/fastly_hosts.py"
MENU_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"

if [ "$1" = "--remove" ]; then
    rm -f "$MENU_DIR/$APP_ID.desktop" "$DESKTOP_DIR/$APP_ID.desktop"
    echo "已移除捷徑。"
    exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "找不到 python3，請先安裝：sudo apt install python3"
    exit 1
fi

mkdir -p "$MENU_DIR"
cat > "$MENU_DIR/$APP_ID.desktop" << EOF
[Desktop Entry]
Type=Application
Name=fastly-hosts
Name[zh_TW]=fastly-hosts（GitHub 下載加速）
Comment=找出最順的 Fastly 路線，加速 GitHub 下載與 X 圖片
Exec=python3 "$SCRIPT"
Icon=network-transmit-receive
Terminal=true
Categories=Network;
EOF
chmod +x "$MENU_DIR/$APP_ID.desktop"
echo "已加入應用程式選單：搜尋「fastly-hosts」即可開啟。"

if [ -d "$DESKTOP_DIR" ]; then
    cp "$MENU_DIR/$APP_ID.desktop" "$DESKTOP_DIR/$APP_ID.desktop"
    chmod +x "$DESKTOP_DIR/$APP_ID.desktop"
    # GNOME 桌面要標記為信任，雙擊才會直接執行
    gio set "$DESKTOP_DIR/$APP_ID.desktop" metadata::trusted true 2>/dev/null || true
    echo "已建立桌面圖示：$DESKTOP_DIR/$APP_ID.desktop"
fi
