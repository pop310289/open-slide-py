# 場景與 API

## 格式

根物件：`schema_version: 1`、`id`、`title`、`width`、`height`、`slides`，可加 `metadata`、`lang`。每頁有唯一的 `id`、`title`、`elements`，可加 `background`、`notes`、`transition`。每個元素包含頁內唯一 `id`、`type`、`x`、`y`、`width`、`height`。

```json
{"schema_version":1,"id":"demo","title":"我的簡報","width":1920,"height":1080,"slides":[{"id":"s1","title":"封面","background":"#142F37","notes":"講者備註","elements":[{"id":"title","type":"text","x":120,"y":250,"width":1680,"height":180,"text":"從設計到落地","font_size":100,"font_family":"Arial","east_asian_font":"PingFang TC","color":"#FFFFFF"}]}]}
```

| type | 主要欄位 |
|---|---|
| `text` | `text`、`font_size`、`font_family`、`east_asian_font`、`color`、`bold`、`align` |
| `rect` / `ellipse` | `fill`、`stroke`、`stroke_width`、`opacity` |
| `line` | `stroke`、`stroke_width`；寬或高可為 0 |
| `image` | `path`、`alt`；path 是 JSON 目錄內的相對路徑 |

所有具體欄位與限制以 `openslide_tk/model.py` 的 `validate_deck` 為準。色彩用六位 `#RRGGBB`，字級與座標以畫布像素計；PPTX 每像素 6350 EMU，文字每像素 0.5 pt。PPTX 畫布邊長 144..8064px、字級 2..2640px。圖片不得超過 25 MiB / 40 megapixels。

`href` 可使用 HTTP(S)、mailto 或 `#slide-id`。`step` 是正整數，同值一起揭露；`transition` 為 `none` 或 `fade`。網頁互動版按實際存在的 step 排序、進入新頁時由零開始，後退至上頁時顯示完整內容。「完整顯示」可暫停逐步模式。PPTX/SVG/靜態 HTML、列印和停用 JavaScript 時均顯示全部元素。

## 樣式（卡片與強調）

| 欄位 | 適用 | 說明 |
|---|---|---|
| `radius` | rect、text | 圓角半徑（像素），最多為短邊的一半 |
| `fill_opacity`、`stroke_opacity` | 有底色或邊框的元素 | 底色與邊框各自的不透明度（0–1），再乘上 `opacity` |
| `gradient` | rect、ellipse、text | 線性漸層，取代 `fill`：`{"angle": 135, "stops": [{"color": "#FFFFFF", "opacity": 0.12, "at": 0}, {"color": "#FFFFFF", "opacity": 0.02, "at": 1}]}`。`angle` 0 由左到右、90 由上到下；2–8 個色標，`at` 0–1 不可遞減，`opacity` 預設 1 |
| `shadow` | rect、ellipse、image | 外陰影：`color`（預設 `#000000`）、`opacity`（0.35）、`blur`（24）、`distance`（8）、`angle`（90，向下） |
| `glow` | rect、ellipse、image | 光暈：`color`（必填）、`opacity`（0.4）、`radius`（16） |
| `highlights` | text | 把文字裡的片語換色或加粗：`[{"text": "承認不確定", "color": "#FF7A3D"}, {"text": "4 倍", "bold": true}]`。片語必須出現在 `text` 裡，每次出現都會套用，重疊時後面的優先 |

PPTX 全部用原生格式（圓角矩形、漸層填色、光暈與外陰影、同一段落的多個文字片段），仍可編輯；HTML/SVG 用 `rx`、`linearGradient`、SVG 濾鏡與巢狀 `tspan`。PowerPoint 沒有背景模糊，所以做不出毛玻璃的模糊；深色背景上用半透明底色、細邊框與光暈就能表現玻璃卡片。光暈與陰影不能用在文字元素；要讓文字區塊浮起來，在文字下方放一個 rect。

## 語言

`lang` 是選填的語言標記，例如 `en-US`、`zh-TW`（字母與連字號，最長 35 字元）。它決定 PPTX 文字與講者備註的校對語言、HTML 的 `lang` 屬性；不是中文（不以 `zh` 開頭）時，靜態 HTML 的外框文字只用英文。未設定時沿用 `zh-TW`（PPTX）、`zh-Hant`（HTML）與中英並列的外框文字。互動播放器的操作介面目前只有中文，`lang` 只改它的 `lang` 屬性。`metadata` 裡的語言欄位不會被讀取。

## 字型與模式差異

預設 Latin 為 Arial、East Asian 為 Microsoft JhengHei。`font_family` 與 `east_asian_font` 各接受單一字型名稱，不接受逗號分隔清單。全案同一軸字型一致時，文件主題、備註與 HTML 外框沿用它；混用或無文字時該軸採預設，個別元素不變。

PPTX 用 `a:latin` / `a:ea` 分寫；當文件 EA 為 PingFang TC 時，兩份 theme 的 Hant 補充字型設為 Microsoft JhengHei，其他明設 face 保留。這只是 theme 字型選擇提示，不保證明設 PingFang 的文字在缺字型的 Windows 上一定採用它；Windows 實機仍未驗證。HTML/SVG 另外生成 CSS fallback stack。未內嵌字型，實際字形由目標裝置決定。

## Python API

從此 skill 根目錄執行，或把它設為 `PYTHONPATH`：

```python
from pathlib import Path
from openslide_tk.model import load_deck, validate_deck
from openslide_tk.storage import save_deck
from openslide_tk.export import export_html, export_svg, svg_markup
from openslide_tk.pptx import export_pptx

source = Path('/path/to/my-deck.json')
deck = load_deck(source)
diagnostics = validate_deck(deck, source.parent)
export_pptx(deck, '/path/to/deck.pptx', source.parent)
export_html(deck, '/path/to/static.html', source.parent)
export_html(deck, '/path/to/player.html', source.parent, interactive=True)
export_svg(deck, 0, '/path/to/first.svg', source.parent)
```

`read_deck` 只解析 JSON（擋下重複鍵、NaN、Infinity），不驗證場景；`load_deck` 解析並驗證。`svg_markup(deck, slide_index, base_dir=None, anchor_map=None)` 回傳轉義後的 SVG 字串，圖片已內嵌。索引從 0 起算，`anchor_map` 只接受本地 `#anchor` 且須覆蓋所有被引用 slide id。同頁 SVG 再次嵌入時需改寫 ID 與 clip-path 引用。

存檔與匯出是原子替換。新檔遵守 umask，覆寫保留目的檔 POSIX mode；不宣稱複製 ACL 或擁有者。無效輸入與輸出失敗不得毀損既有檔案。
