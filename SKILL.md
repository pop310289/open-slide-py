---
name: open-slide-py
description: 用 open-slide-py（open-slide 的 Python 標準函式庫改寫版）製作或修改場景 JSON，匯出可編輯 PPTX、SVG、靜態 HTML 或離線網頁播放器。適用「用 OpenSlide 做簡報／投影片」「匯出成 PowerPoint」「把簡報做成手機網頁」。不處理既有 PPTX 匯入、原版 open-slide 比較或服務部署。
---

# open-slide-py 原生簡報

此 skill 只負責製作、修改與驗收原生簡報。資料夾內含完整 runtime，可獨立複製使用；只需要 Python 3.10+ 的標準函式庫，不需安裝套件。沒有圖形編輯器，直接編輯場景 JSON。所有下列指令從此 skill 根目錄執行，輸出路徑改成使用者專案的絕對路徑。

## 製作流程

1. 依使用者的受眾、內容與用途安排每頁論點；先讀 [製作與版面](references/authoring.md)。修改時以既有 JSON 為來源，不重建成品來冒充原稿。
2. 用 `python3 -m openslide_tk init /path/to/my-deck.json` 建立起點，或複製 `examples/demo.json` 到新案。簡報不是中文時，在 JSON 頂層加 `"lang": "en-US"` 這類語言標記，否則 PPTX 會標成中文、HTML 外框會有中文字（見[場景與 API](references/scene.md) 的「語言」）。按 [場景與 API](references/scene.md) 編輯；圖片與 JSON 放在同一個專案目錄內。
3. 驗證後匯出所需格式；保留場景 JSON 與素材，文字、數據圖與幾何圖解使用原生元素。
4. 按 [驗收](references/verification.md) 檢查實際輸出。測試、視覺檢查、裝置操作與 Office 編輯往返分開回報，只有本次重跑的結果能標示為通過。

```sh
python3 -m openslide_tk validate /path/to/my-deck.json
python3 -S -m openslide_tk export /path/to/my-deck.json /path/to/my-deck.pptx
python3 -S -m openslide_tk export /path/to/my-deck.json /path/to/reading.html
python3 -S -m openslide_tk export /path/to/my-deck.json /path/to/player.html --interactive
```

## 必須保留的契約

- 核心與作者腳本只用 Python 標準函式庫。不得引入 React、ReactDOM、Next.js、JSX/TSX 或以內嵌瀏覽器包裝 React。原生 `.js` 只處理網頁互動；Python 匯出不需要 Node。
- 預設 HTML 靜態且無 JavaScript；`--interactive` 使用包內原生播放器。兩種輸出都要保留回歸。場景與備註作為轉義文字／SVG，不能用 `innerHTML` 執行；互動版內嵌 CSS/JS 的 CSP hash 隨內容計算（靜態版未設 CSP meta）。
- `font_family`、`east_asian_font` 各是一個字型名稱。PPTX 分別寫 Latin／East Asian，CSS fallback 只用於 HTML/SVG。字型宣告不等於嵌入、實際替代或 Windows 驗證。
- 保留原子寫檔、輸入驗證與失敗不覆蓋原檔的行為。修改 runtime 後，新輸出須重新檢查內容與渲染。

## 邊界與維護

PPTX 不含網頁逐步動畫，PDF 可由 HTML 列印或外部 Office 轉檔，沒有原生 PDF writer。不支援任意 PPTX 匯入、影片、Morph 或完整瀏覽器 CSS。

本 skill 不負責部署，也不修改任何服務或路由。它不含上游 React 版的 adapter、案例與部署腳本。與上游 open-slide 的關係、收錄範圍與已驗證／未驗證的項目見 [來源與範圍](references/provenance.md)。
