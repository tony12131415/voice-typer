# Voice Typer

macOS 上用 [whisper.cpp](https://github.com/ggml-org/whisper.cpp)（GGML 版 Whisper，跑在 Apple Silicon 的 Metal GPU 上）做的語音輸入小工具。

連按兩下 **Fn（🌐）** 鍵開始講話，再連按兩下停止，會自動轉錄（中英文自動偵測，簡體轉繁體）並貼到目前游標所在的欄位。

> **貼上的位置就是你的滑鼠游標／目前作用中的輸入框。** 換句話說，講話之前先把游標點到你想要文字出現的地方（Notion、備忘錄、聊天視窗、程式碼編輯器都可以），結束錄音後轉錄結果就會直接貼在那裡，不用自己再複製貼上一次。

## 功能

- **常駐 whisper-server**：模型只在啟動時載入一次，之後每次錄音只送 HTTP 請求過去轉錄，不用每次重新載入模型（省下大部分等待時間）
- **Fn 雙擊觸發**：用底層 Quartz event tap 偵測連續兩次按 Fn 鍵，開始/結束用同一個手勢切換
- **Dock 選單**：右鍵點 Dock 圖示可以看到 `Start Transcribing` / `End Transcribing` / `Quit`，狀態不對的選項會自動反灰（例如辨識中兩個都不能點）
- **簡轉繁**：轉錄結果用 [OpenCC](https://github.com/BYVoid/OpenCC)（`s2twp`）從簡體轉成繁體台灣用語
- **自動去除多餘換行**：whisper 每個語音片段之間預設會插入換行，這裡會還原成連續的自然斷句
- **Session 逐字稿**：每次轉錄結果也會即時 append 進一個 TextEdit 視窗（`~/Documents/Voice Typer Transcript.txt`），方便回頭找剛剛講了什麼，就算貼上的地方一時找不到也不會遺失內容
- **狀態通知**：沒有終端機視窗時（打包成 App 執行），用 macOS 系統通知顯示「開始錄音」「⏳ 辨識中」「轉錄結果」等狀態，log 寫到 `~/Library/Logs/VoiceTyper.log`

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

**系統設定 → 鍵盤 → 「按下 🌐 (Fn) 鍵時」** → 改成 **「不執行任何動作」**，否則雙擊 Fn 會跟系統原本的 Fn 鍵功能（Emoji 選單、口述聽寫等）衝突。

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

雙擊 `/Applications/Voice Typer.app`（或用 Launchpad）啟動。之後可以：
- 連按兩下 Fn 開始/結束錄音，或
- 右鍵 Dock 圖示，用選單操作

結束程式：Cmd+Q，或右鍵 Dock 圖示選 `Quit`。

## 調整

- 想要更快但準確度略低：`voice_typer.py` 裡 `start_whisper_server()` 的 `-bo 1` 已經是貪婪解碼（最快設定）
- 想換語言限定（例如只認英文）：把 `LANGUAGE = "auto"` 改成 `"en"` / `"zh"` 等
- 想改雙擊時間窗：改 `DOUBLE_PRESS_WINDOW`（秒）
- 想改逐字稿存放位置：改 `TRANSCRIPT_DIR` / `TRANSCRIPT_NAME`

## 已知限制

- 辨識是整段錄完才送出去，錄越長等越久（沒有即時邊講邊轉錄）
- Fn 雙擊偵測跟系統的 event tap 機制綁定，如果 macOS 認定回呼太慢會自動停用 tap；目前辨識工作都丟到背景執行緒處理，正常情況下不會觸發，但如果哪天又發生「按了沒反應」，可以先查 log 裡有沒有 `event tap 被系統停用` 這行
