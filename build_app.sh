#!/bin/bash
# 產生 Voice Typer.app，安裝到 /Applications
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$HOME/venvs/breeze-asr"
APP_DIR="/Applications/Voice Typer.app"

mkdir -p "$APP_DIR/Contents/MacOS"

cat > "$APP_DIR/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>Voice Typer</string>
    <key>CFBundleDisplayName</key>
    <string>Voice Typer</string>
    <key>CFBundleIdentifier</key>
    <string>com.tony.voicetyper</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundleExecutable</key>
    <string>VoiceTyper</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>11.0</string>
    <key>NSMicrophoneUsageDescription</key>
    <string>Voice Typer 需要使用麥克風來錄下你要轉錄的語音。</string>
</dict>
</plist>
PLIST

cat > "$APP_DIR/Contents/MacOS/VoiceTyper" << LAUNCHER
#!/bin/bash
LOG="\$HOME/Library/Logs/VoiceTyper.log"
mkdir -p "\$(dirname "\$LOG")"

{
    echo "=== \$(date) ==="
    source "$VENV_DIR/bin/activate"
    exec python3 -u "$SCRIPT_DIR/voice_typer.py"
} >> "\$LOG" 2>&1
LAUNCHER

chmod +x "$APP_DIR/Contents/MacOS/VoiceTyper"

echo "已建立: $APP_DIR"
echo ""
echo "第一次執行前，記得到「系統設定 → 隱私權與安全性」把 Voice Typer 加進："
echo "  - 輸入監控 (Input Monitoring)"
echo "  - 輔助使用 (Accessibility)"
