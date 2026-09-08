"""
py2app 打包設定。用 alias mode 建置（`python3 setup.py py2app -A`），
產生一個真正的原生 App bundle（不再借用 Homebrew Python.app 的身份），
但執行時仍然參照 venv 裡的套件，不整包內嵌，避免 numpy/sounddevice
這類原生擴充套件被打包時出問題。
"""

from setuptools import setup

APP = ["voice_typer.py"]

OPTIONS = {
    "argv_emulation": False,
    "iconfile": "icon.icns",
    "plist": {
        "CFBundleName": "Voice Typer",
        "CFBundleDisplayName": "Voice Typer",
        "CFBundleIdentifier": "com.tony.voicetyper",
        "CFBundleVersion": "1.0",
        "CFBundleShortVersionString": "1.0",
        "LSMinimumSystemVersion": "11.0",
        "NSMicrophoneUsageDescription": "Voice Typer 需要使用麥克風來錄下你要轉錄的語音。",
    },
}

setup(
    app=APP,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
