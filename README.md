# Voice Typer

macOS 上用 [whisper.cpp](https://github.com/ggml-org/whisper.cpp)（GGML 版 Whisper，跑在 Apple Silicon 的 Metal GPU 上）做的語音輸入小工具。

按下 `Cmd+Shift+V` 開始講話，再按一次停止，會自動轉錄（中英文自動偵測，簡體轉繁體）並貼到目前游標所在的欄位。

## 運作方式

- 啟動時會在背景常駐一個 `whisper-server`，模型只載入一次；之後每次錄音只送 HTTP 請求過去轉錄，不用每次重新載入模型（省下大部分等待時間）
- 用底層 Quartz event tap 攔截 `Cmd+Shift+V`，讓它不會同時觸發系統內建的「貼上並符合樣式」
- 轉錄結果用 [OpenCC](https://github.com/BYVoid/OpenCC)（`s2twp`）從簡體轉成繁體台灣用語
- 沒有終端機視窗時（打包成 App 執行），用 macOS 系統通知顯示狀態，log 寫到 `~/Library/Logs/VoiceTyper.log`

## 安裝

### 1. 裝 whisper.cpp

```bash
brew install whisper-cpp
```

### 2. 下載 GGML 模型

```bash
mkdir -p ~/models/whisper-cpp
curl -L -o ~/models/whisper-cpp/ggml-large-v3-turbo.bin \
  "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin"
```

其他模型大小（tiny/base/small/medium/large-v3）可以到 [ggerganov/whisper.cpp 的 Hugging Face repo](https://huggingface.co/ggerganov/whisper.cpp) 選，速度和準確度自己抓平衡。改路徑的話要同步改 `voice_typer.py` 裡的 `MODEL_PATH`。

### 3. 建立 Python 環境

```bash
python3 -m venv ~/venvs/breeze-asr
source ~/venvs/breeze-asr/bin/activate
pip install -r requirements.txt
```

### 4.（可選）打包成 App，放到 Applications

```bash
./build_app.sh
```

會在 `/Applications/Voice Typer.app` 產生一個可以雙擊開啟的 App。

## 權限設定（macOS 必要步驟）

不管是用 Terminal 手動跑，還是打包成 App 執行，都要把「實際執行的那個東西」加進系統權限：

**系統設定 → 隱私權與安全性**
- **輸入監控**：加入你用的終端機 App（例如 Terminal.app），或打包後的 `Voice Typer.app`
- **輔助使用**：同上

第一次錄音時系統會另外跳出麥克風權限詢問，允許即可。

> 手動用 Terminal 跑的話，權限要加在啟動 python 的那個終端機 App 身上，不是 python 執行檔本身（macOS 對命令列工具的權限判定，通常認的是「啟動它的那個 App」）。打包成 `.app` 之後，因為換了一個新的 App 身份，需要重新對 `Voice Typer.app` 授權一次。

## 使用方式

**手動執行（方便看 log/除錯）：**

```bash
source ~/venvs/breeze-asr/bin/activate
python3 -u voice_typer.py
```

Ctrl+C 結束（會一併關閉背景的 whisper-server）。

**打包成 App 之後：**

雙擊 `/Applications/Voice Typer.app`（或用 Launchpad）。結束時 Cmd+Q 或右鍵 Dock 圖示選 Quit。

## 調整

- 想要更快但準確度略低：`voice_typer.py` 裡 `start_whisper_server()` 的 `-bo 1` 已經是貪婪解碼（最快設定）
- 想換語言限定（例如只認英文）：把 `LANGUAGE = "auto"` 改成 `"en"` / `"zh"` 等
- 想改快捷鍵：改 `HOTKEY_KEYCODE`（macOS virtual keycode）和 `HOTKEY_FLAGS`
