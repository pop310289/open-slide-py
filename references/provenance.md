# 來源與範圍

open-slide-py 依 open-slide（作者 Yiwei Ho，MIT 授權，見 `LICENSE-UPSTREAM`）的行為與設計概念，用 Python 標準函式庫與 Tcl/Tk 重新實作。它不是 open-slide 的官方版本，也和醫學影像函式庫 OpenSlide 無關。本專案以 MIT 授權釋出（見 `LICENSE`）。

## 收錄範圍

- `openslide_tk/`：場景模型與驗證、PPTX／SVG／靜態 HTML／互動播放器匯出、Tk 桌面編輯器，以及播放器用的 CSS/JS。
- `tests/`：核心回歸測試。其中 4 項需要實際的 Tk 視窗，預設略過，設 `OPENSLIDE_GUI_TEST=1` 才會執行。
- `examples/demo.json`：三頁示範簡報。
- `scripts/verify_skill.py`：執行測試，以 `python3 -S` 匯出四種格式，並核對文字、備註與重複匯出的結果。
- 不含上游 React/Node 版的 adapter、案例成品、部署腳本與比較工具。

## 已驗證與未驗證

- 已驗證（macOS、Python 3.14 與 3.9）：118 項測試；四種格式都能在 `python3 -S` 下匯出；同一份場景重複匯出的 PPTX 位元組相同；PPTX 保留每頁文字與講者備註；靜態 HTML 不含 JavaScript。4 項 GUI 測試曾在 macOS 的實際 Tk 視窗下通過。
- 未驗證：在 PowerPoint／Keynote 開啟、修改、存檔後再開的編輯往返；Windows 的字型替代與版面；實體手機上的觸控操作。字型只宣告、不內嵌，實際字形由開啟的裝置決定。
- 已知限制：互動播放器的操作介面、桌面編輯器與 `init` 的範例簡報只有中文；PPTX 文字預先斷行（每行一個段落、不自動換行），各渲染器斷行位置一致，但在 PowerPoint 裡修改時不會重新排版；`line` 只能從外框左上畫到右下；`validate` 會估算文字溢出，但不檢查文字框互相重疊；不支援 PPTX 匯入、影片、Morph 轉場或原生 PDF 輸出（可由 HTML 列印成 PDF）。
