#!/bin/bash
# 用 py2app（alias mode）建置 Voice Typer.app，安裝到 /Applications。
# alias mode 只建立一個原生的 App bundle 殼，執行時仍然參照 venv 裡的套件，
# 不整包內嵌 numpy/sounddevice 這類原生擴充套件，避免打包出問題。
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$HOME/venvs/breeze-asr"

cd "$SCRIPT_DIR"
source "$VENV_DIR/bin/activate"

rm -rf build dist
python3 setup.py py2app -A

rm -rf "/Applications/Voice Typer.app"
cp -R "dist/Voice Typer.app" "/Applications/"

# build/dist 留在專案資料夾裡的話，Spotlight/Launchpad 會把它們也當成
# 獨立的 App 顯示出來，造成看起來有兩個 Voice Typer，用完就清掉。
rm -rf build dist

echo ""
echo "已建立: /Applications/Voice Typer.app"
echo ""
echo "第一次執行前，記得："
echo "1. 系統設定 → 隱私權與安全性 → 輸入監控 → 加入 Voice Typer"
echo "2. 系統設定 → 隱私權與安全性 → 輔助使用 → 加入 Voice Typer"
echo "3. 系統設定 → 鍵盤 → 「按下 🌐 (Fn) 鍵時」→ 設成「不執行任何動作」"
echo ""
echo "（如果是重新打包更新既有的 App，因為 bundle 內容變了，"
echo " 上面兩個權限通常需要重新授權一次）"
