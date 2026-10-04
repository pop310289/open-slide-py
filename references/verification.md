# 驗收

## 核心與獨立副本

```sh
python3 -S -m unittest discover -s tests -v
python3 scripts/verify_skill.py --output /path/to/verification.json
python3 scripts/verify_skill.py --gui --output /path/to/gui-verification.json
```

驗證器執行所附核心測試、以 `python3 -S` 匯出 PPTX/SVG/靜態 HTML/互動 HTML、核對 PPTX 文字與備註、隔開 ZIP 時間戳精度後比對兩次匯出 bytes，並記錄結果。測試可選用已存在的 Node 檢查 JS 狀態；Node 不是匯出相依。

`--gui` 會真的開 Tk 視窗，檢查表單、字型與示範各頁邊界，且要求測試零略過。缺 `wish`、顯示環境、Tcl 或選用 JS 測試解譯器時，要記錄未驗證；不能把略過當成通過。預設不啟動 GUI，報告保留略過數。

要證明可攜性，先只複製此資料夾到乾淨暫存目錄，清除 `PYTHONPATH` / `PYTHONHOME` 並設定 `PYTHONNOUSERSITE=1`，在副本執行上述驗證；不能使用來源 repo 的 cases、素材、vendor 或 site-packages。

## 每份成品

- `validate` 零錯誤；警告逐項檢視。逐頁比對文字、數字、單位、備註與連結。
- 以實際渲染尺寸看全頁和細節，記錄溢出、裁切、圖說對應、來源與註腳可讀性。結構測試不代表視覺品質。
- 互動 HTML 要操作鍵盤、工具列、觸控／滑動、逐步顯示、頁目錄、備註與計時。確認離線可用、CSP 無錯誤、停用 JS 和列印仍有完整內容。桌面／手機／模擬器分別標示，不繼承靜態版的零 JS 結論。
- 在 Office／Keynote 實際修改文字與物件位置、匯出 PPTX、重開並確認修改仍在，才能稱為編輯往返。記錄 app/OS、輸入與輸出 SHA-256、操作與渲染證據。只有開檔不算完成往返。
- 字型分別驗收 OOXML 宣告、作業系統實際解析、輸出渲染／PDF 字型。未在 Windows 實測就寫未驗證，不能以 theme 宣告冒充跨平台保真。

輸出或來源改變後，過期的 hash、畫面及往返結果只可作歷史記錄。交付來源 JSON、素材、要求的成品及與版本一致的驗收摘要；本 skill 自帶的範例測試不替新案背書。
