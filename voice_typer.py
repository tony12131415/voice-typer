"""
whisper.cpp (GGML) 語音輸入工具
啟動時會先在背景常駐一個 whisper-server（模型只載入一次），
之後每次錄音只送 HTTP 請求過去轉錄，不用每次重新載入模型。

連按兩下 Fn（🌐）鍵開始錄音，再連按兩下停止 → 自動轉錄（簡轉繁）並貼到目前作用中的欄位，
同時把這句話 append 進 TextEdit 裡的 session 逐字稿，方便回頭找剛剛講了什麼。
（需要先到「系統設定 → 鍵盤 → 按下 🌐 鍵時」設成「不執行任何動作」，否則會跟系統原本的
Fn 鍵功能（Emoji 選單/口述聽寫等）衝突。）

實際辨識工作丟到背景執行緒處理，讓按鍵事件的回呼可以馬上返回——
如果卡在回呼裡面太久，macOS 會自動停用這個 event tap，導致按鍵完全沒反應。

右鍵點 Dock 圖示可以看到 Start Transcribing / End Transcribing / Quit 選單，
Quit 跟 Ctrl+C（終端機執行時）都會一併關閉背景的 whisper-server。
"""

import atexit
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

# 用 Finder/py2app 雙擊開啟時，這個行程完全沒有 LANG/LC_CTYPE 這類 locale
# 環境變數（不像從 Terminal 跑會繼承 shell 的設定）。pbcopy 這類系統工具會
# 依賴這些變數判斷輸入內容的編碼，沒有的話會用錯誤的編碼解讀我們傳進去的
# UTF-8 位元組，貼到剪貼簿上的中文字就會變成亂碼。這裡用 setdefault 補上，
# 已經有設定的話（例如 Terminal 手動執行）就不覆蓋。
os.environ.setdefault("LANG", "en_US.UTF-8")
os.environ.setdefault("LC_ALL", "en_US.UTF-8")

# 用 App 雙擊開啟時沒有終端機可以看輸出，把 stdout/stderr 導進 log 檔；
# 用 Terminal 手動跑（有 tty）的話維持印在畫面上方便除錯。
if not sys.stdout.isatty():
    LOG_PATH = Path.home() / "Library" / "Logs" / "VoiceTyper.log"
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _log_file = open(LOG_PATH, "a", buffering=1, encoding="utf-8")
    sys.stdout = _log_file
    sys.stderr = _log_file
    print(f"=== {datetime.now()} ===")

import numpy as np
import opencc
import Quartz
import requests
import sounddevice as sd
import soundfile as sf
from Cocoa import NSApplication, NSMenu, NSMenuItem, NSObject
from PyObjCTools import AppHelper
from pynput.keyboard import Controller as KeyboardController
from pynput.keyboard import Key

HOTKEY_HINT = "連按兩下 Fn"
DOUBLE_PRESS_WINDOW = 0.5  # 秒，兩次按 Fn 之間的最大間隔

SAMPLE_RATE = 16000
chinese_converter = opencc.OpenCC("s2twp")  # 簡體 -> 繁體（台灣用語）

WHISPER_SERVER_BIN = "/opt/homebrew/bin/whisper-server"
MODEL_PATH = str(Path.home() / "models" / "whisper-cpp" / "ggml-large-v3-turbo.bin")
LANGUAGE = "auto"  # 中英混合自動偵測
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8090
INFERENCE_URL = f"http://{SERVER_HOST}:{SERVER_PORT}/inference"

TRANSCRIPT_DIR = Path.home() / "Documents"
TRANSCRIPT_NAME = "Voice Typer Transcript.txt"
TRANSCRIPT_PATH = TRANSCRIPT_DIR / TRANSCRIPT_NAME

kb = KeyboardController()
recording = False
is_processing = False
current_frames = None
stream = None
lock = threading.Lock()


def _escape_for_osascript(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def notify(title: str, message: str) -> None:
    script = f'display notification "{_escape_for_osascript(message)}" with title "{_escape_for_osascript(title)}"'
    subprocess.run(["osascript", "-e", script])


def _append_line_to_transcript_doc(line: str) -> None:
    """透過 AppleScript 操作 TextEdit 本身來寫入，避免 Python 直接改檔案
    跟 TextEdit 記憶體內容打架（外部檔案變動可能讓 TextEdit 跳出提示對話框）。
    這個函式是 best-effort：任何失敗都靜默吞掉，不影響貼上流程。
    """
    escaped = _escape_for_osascript(line)
    script = f'''
    tell application "TextEdit"
        if not (exists document "{TRANSCRIPT_NAME}") then
            open POSIX file "{TRANSCRIPT_PATH}"
        end if
        activate
        set targetDoc to document "{TRANSCRIPT_NAME}"
        set text of targetDoc to (text of targetDoc) & "{escaped}" & linefeed
        save targetDoc
    end tell
    '''
    try:
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
    except Exception as e:
        print(f"[transcript] 寫入 TextEdit 失敗（忽略，不影響貼上）: {e}")


def open_transcript_window() -> None:
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    if not TRANSCRIPT_PATH.exists():
        TRANSCRIPT_PATH.write_text("", encoding="utf-8")

    divider = f"===== Session 開始 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ====="
    _append_line_to_transcript_doc(divider)


def append_to_transcript(text: str) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    _append_line_to_transcript_doc(f"[{timestamp}] {text}")


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

open_transcript_window()

print(f"whisper.cpp server 就緒（模型: {MODEL_PATH}）")
print(f"按 {HOTKEY_HINT} 開始/停止錄音，或右鍵 Dock 圖示操作。")
notify("Voice Typer", f"已就緒，按 {HOTKEY_HINT} 開始錄音")


def start_recording():
    global recording, current_frames, stream
    with lock:
        if recording or is_processing:
            return
        frames = []
        current_frames = frames

        # 每次錄音用自己專屬的 frames list（closure 綁定），就算上一個 stream
        # 的 callback 延遲觸發，也只會寫進上一段已經用完的舊 list，不會污染新的這段。
        def callback(indata, frame_count, time_info, status):
            frames.append(indata.copy())

        recording = True
        stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, callback=callback)
        stream.start()
    print("🔴 開始錄音...")
    notify("Voice Typer", "🔴 開始錄音")


def transcribe(wav_path: str) -> str:
    with open(wav_path, "rb") as f:
        resp = requests.post(INFERENCE_URL, files={"file": f}, data={"response_format": "json"})
    resp.raise_for_status()
    text = resp.json().get("text", "").strip()
    # whisper-server 每個語音片段之間會插入換行符號，但片段本身通常已經
    # 帶有自然的空格/標點分隔，直接把換行去掉即可還原成連續的句子。
    text = text.replace("\n", "")
    return chinese_converter.convert(text)


def stop_recording_and_transcribe():
    """只做『停止錄音』這件快事，馬上返回。實際辨識丟到背景執行緒，
    避免按鍵事件的回呼卡住太久被 macOS 判定逾時、自動停用 event tap。
    """
    global recording, stream, is_processing, current_frames
    with lock:
        if not recording:
            return
        recording = False
        is_processing = True
        stream.stop()
        stream.close()
        frames = current_frames
        current_frames = None
    print("⏹ 停止錄音，轉錄中...")
    notify("Voice Typer", "⏳ 辨識中，請稍候...")

    threading.Thread(target=_process_recording, args=(frames,), daemon=True).start()


def _process_recording(frames) -> None:
    global is_processing
    try:
        if not frames:
            print("沒有錄到聲音")
            notify("Voice Typer", "沒有錄到聲音")
            return

        audio = np.concatenate(frames, axis=0).flatten()

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
            sf.write(tmp.name, audio, SAMPLE_RATE, subtype="PCM_16")
            text = transcribe(tmp.name)

        print("轉錄結果:", text)

        if text:
            paste_via_clipboard(text)
            append_to_transcript(text)
            notify("Voice Typer", text[:80])
        else:
            notify("Voice Typer", "沒有聽清楚，請再試一次")
    finally:
        is_processing = False


def paste_via_clipboard(text: str) -> None:
    old_clipboard = subprocess.run(
        ["pbpaste"], capture_output=True, text=True, encoding="utf-8"
    ).stdout
    subprocess.run(["pbcopy"], input=text, text=True, encoding="utf-8")
    time.sleep(0.05)

    kb.press(Key.cmd)
    kb.press("v")
    kb.release("v")
    kb.release(Key.cmd)

    time.sleep(0.3)
    subprocess.run(["pbcopy"], input=old_clipboard, text=True, encoding="utf-8")


def toggle():
    if is_processing:
        print("目前正在辨識中，忽略這次觸發")
        return
    if recording:
        stop_recording_and_transcribe()
    else:
        start_recording()


fn_previously_down = False
last_fn_down_time = 0.0


def event_tap_callback(proxy, event_type, event, refcon):
    global fn_previously_down, last_fn_down_time

    # macOS 在回呼太慢時會自動停用 tap，這裡收到停用通知就立刻重新啟用，
    # 當作保險（正常情況下背景執行緒化之後回呼應該都很快，不會被停用）。
    if event_type in (Quartz.kCGEventTapDisabledByTimeout, Quartz.kCGEventTapDisabledByUserInput):
        print("[debug] event tap 被系統停用，重新啟用")
        Quartz.CGEventTapEnable(tap, True)
        return event

    if event_type == Quartz.kCGEventFlagsChanged:
        flags = Quartz.CGEventGetFlags(event)
        fn_down = bool(flags & Quartz.kCGEventFlagMaskSecondaryFn)

        if fn_down and not fn_previously_down:
            now = time.monotonic()
            if now - last_fn_down_time <= DOUBLE_PRESS_WINDOW:
                last_fn_down_time = 0.0  # 重置，避免連續按三下又誤判成第二次雙擊
                toggle()
            else:
                last_fn_down_time = now

        fn_previously_down = fn_down

    return event


tap = Quartz.CGEventTapCreate(
    Quartz.kCGSessionEventTap,
    Quartz.kCGHeadInsertEventTap,
    Quartz.kCGEventTapOptionDefault,
    Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged),
    event_tap_callback,
    None,
)
if tap is None:
    raise RuntimeError("無法建立 event tap，請確認 Voice Typer 已加入「輸入監控」與「輔助使用」權限")

run_loop_source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
Quartz.CFRunLoopAddSource(Quartz.CFRunLoopGetMain(), run_loop_source, Quartz.kCFRunLoopCommonModes)
Quartz.CGEventTapEnable(tap, True)


def quit_app() -> None:
    print("結束程式")
    try:
        server_proc.terminate()
    except Exception:
        pass
    AppHelper.stopEventLoop()


class AppDelegate(NSObject):
    def applicationDockMenu_(self, sender):
        menu = NSMenu.alloc().init()

        start_title = f"Start Transcribing  {HOTKEY_HINT}"
        stop_title = f"End Transcribing  {HOTKEY_HINT}"
        if is_processing:
            stop_title = "⏳ Transcribing..."

        start_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            start_title, "startTranscribing:", ""
        )
        start_item.setTarget_(self)
        start_item.setEnabled_(not recording and not is_processing)
        menu.addItem_(start_item)

        stop_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            stop_title, "endTranscribing:", ""
        )
        stop_item.setTarget_(self)
        stop_item.setEnabled_(recording and not is_processing)
        menu.addItem_(stop_item)

        menu.addItem_(NSMenuItem.separatorItem())

        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quit", "quitFromMenu:", "")
        quit_item.setTarget_(self)
        menu.addItem_(quit_item)

        return menu

    def startTranscribing_(self, sender):
        start_recording()

    def endTranscribing_(self, sender):
        stop_recording_and_transcribe()

    def quitFromMenu_(self, sender):
        quit_app()


def handle_sigterm(signum, frame):
    quit_app()


signal.signal(signal.SIGTERM, handle_sigterm)
signal.signal(signal.SIGINT, handle_sigterm)  # 確保用 Terminal 跑時 Ctrl+C 也能可靠結束

app = NSApplication.sharedApplication()
delegate = AppDelegate.alloc().init()
app.setDelegate_(delegate)

try:
    AppHelper.runEventLoop()
except KeyboardInterrupt:
    quit_app()

sys.exit(0)
