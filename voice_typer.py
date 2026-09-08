"""
whisper.cpp (GGML) 語音輸入工具
啟動時會先在背景常駐一個 whisper-server（模型只載入一次），
之後每次錄音只送 HTTP 請求過去轉錄，不用每次重新載入模型。
按 Cmd+Shift+V 開始錄音，再按一次停止 → 自動轉錄（簡轉繁）並貼到目前作用中的欄位。
用底層 Quartz event tap 攔截 Cmd+Shift+V，讓它不會同時觸發系統的「貼上並符合樣式」。
用 Ctrl+C（終端機執行時）或 Cmd+Q / Dock 右鍵結束（打包成 App 執行時）結束程式，
兩種方式都會一併關閉背景的 whisper-server。
"""

import atexit
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import opencc
import Quartz
import requests
import sounddevice as sd
import soundfile as sf
from pynput.keyboard import Controller as KeyboardController
from pynput.keyboard import Key

# Cmd+Shift+V：virtual keycode 9 = 'v'（ANSI 鍵盤配置）
HOTKEY_KEYCODE = 9
HOTKEY_FLAGS = Quartz.kCGEventFlagMaskCommand | Quartz.kCGEventFlagMaskShift
RELEVANT_FLAGS_MASK = (
    Quartz.kCGEventFlagMaskCommand
    | Quartz.kCGEventFlagMaskShift
    | Quartz.kCGEventFlagMaskAlternate
    | Quartz.kCGEventFlagMaskControl
)

SAMPLE_RATE = 16000
chinese_converter = opencc.OpenCC("s2twp")  # 簡體 -> 繁體（台灣用語）

WHISPER_SERVER_BIN = "/opt/homebrew/bin/whisper-server"
MODEL_PATH = str(Path.home() / "models" / "whisper-cpp" / "ggml-large-v3-turbo.bin")
LANGUAGE = "auto"  # 中英混合自動偵測
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8090
INFERENCE_URL = f"http://{SERVER_HOST}:{SERVER_PORT}/inference"

kb = KeyboardController()
recording = False
audio_frames = []
stream = None
lock = threading.Lock()


def _escape_for_osascript(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def notify(title: str, message: str) -> None:
    script = f'display notification "{_escape_for_osascript(message)}" with title "{_escape_for_osascript(title)}"'
    subprocess.run(["osascript", "-e", script])


def start_whisper_server() -> subprocess.Popen:
    proc = subprocess.Popen(
        [
            WHISPER_SERVER_BIN,
            "-m", MODEL_PATH,
            "-l", LANGUAGE,
            "-bo", "1",  # 貪婪解碼，優先求快，適合即時語音輸入
            "--host", SERVER_HOST,
            "--port", str(SERVER_PORT),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print("啟動 whisper-server 中，載入模型（第一次約需幾秒）...")
    for _ in range(60):
        try:
            requests.get(f"http://{SERVER_HOST}:{SERVER_PORT}", timeout=1)
            break
        except requests.exceptions.ConnectionError:
            time.sleep(1)
    else:
        raise RuntimeError("whisper-server 啟動逾時，請檢查 whisper-server 是否正常安裝")
    return proc


server_proc = start_whisper_server()
atexit.register(server_proc.terminate)

print(f"whisper.cpp server 就緒（模型: {MODEL_PATH}）")
print("按 Cmd+Shift+V 開始/停止錄音，按 Ctrl+C 結束程式。")
notify("Voice Typer", "已就緒，按 Cmd+Shift+V 開始錄音")


def audio_callback(indata, frames, time_info, status):
    if recording:
        audio_frames.append(indata.copy())


def start_recording():
    global recording, audio_frames, stream
    with lock:
        if recording:
            return
        audio_frames = []
        recording = True
        stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, callback=audio_callback)
        stream.start()
    print("🔴 開始錄音...")
    notify("Voice Typer", "🔴 開始錄音")


def transcribe(wav_path: str) -> str:
    with open(wav_path, "rb") as f:
        resp = requests.post(INFERENCE_URL, files={"file": f}, data={"response_format": "json"})
    resp.raise_for_status()
    text = resp.json().get("text", "").strip()
    return chinese_converter.convert(text)


def stop_recording_and_transcribe():
    global recording, stream
    with lock:
        if not recording:
            return
        recording = False
        stream.stop()
        stream.close()
    print("⏹ 停止錄音，轉錄中...")

    if not audio_frames:
        print("沒有錄到聲音")
        return

    audio = np.concatenate(audio_frames, axis=0).flatten()

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
        sf.write(tmp.name, audio, SAMPLE_RATE, subtype="PCM_16")
        text = transcribe(tmp.name)

    print("轉錄結果:", text)

    if text:
        paste_via_clipboard(text)
        notify("Voice Typer", text[:80])
    else:
        notify("Voice Typer", "沒有聽清楚，請再試一次")


def paste_via_clipboard(text: str) -> None:
    old_clipboard = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout
    subprocess.run(["pbcopy"], input=text, text=True)
    time.sleep(0.05)

    kb.press(Key.cmd)
    kb.press("v")
    kb.release("v")
    kb.release(Key.cmd)

    time.sleep(0.3)
    subprocess.run(["pbcopy"], input=old_clipboard, text=True)


def toggle():
    if recording:
        stop_recording_and_transcribe()
    else:
        start_recording()


def event_tap_callback(proxy, event_type, event, refcon):
    if event_type == Quartz.kCGEventKeyDown:
        keycode = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
        flags = Quartz.CGEventGetFlags(event) & RELEVANT_FLAGS_MASK
        if keycode == HOTKEY_KEYCODE and flags == HOTKEY_FLAGS:
            toggle()
            return None  # 吞掉事件，不讓它傳到目前作用中的 App（避免觸發系統的貼上）
    return event


tap = Quartz.CGEventTapCreate(
    Quartz.kCGSessionEventTap,
    Quartz.kCGHeadInsertEventTap,
    Quartz.kCGEventTapOptionDefault,
    Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown),
    event_tap_callback,
    None,
)
if tap is None:
    raise RuntimeError("無法建立 event tap，請確認 Terminal 已加入「輸入監控」與「輔助使用」權限")

run_loop_source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
Quartz.CFRunLoopAddSource(Quartz.CFRunLoopGetCurrent(), run_loop_source, Quartz.kCFRunLoopCommonModes)
Quartz.CGEventTapEnable(tap, True)

def handle_sigterm(signum, frame):
    raise SystemExit(0)


signal.signal(signal.SIGTERM, handle_sigterm)

try:
    while True:
        Quartz.CFRunLoopRunInMode(Quartz.kCFRunLoopDefaultMode, 1.0, False)
except (KeyboardInterrupt, SystemExit):
    print("結束程式")
    sys.exit(0)
