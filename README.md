# ESG 承諾與證據標註（ESG Promise & Evidence Annotation）

使用 Gemini 自動標註繁體中文企業永續報告書段落，抽取 **ESG 承諾（promise）** 與 **對應證據（evidence）**，並判斷 **驗證時程** 與 **證據品質**。

跑一行指令即可完成整個流程：讀取資料 → 逐筆呼叫 Gemini（schema 強制結構化輸出）→ 存結果 → 印出統計。

---

## Quick Start

```bash
# 1. 安裝相依套件
pip install -r requirements.txt

# 2. 設定 API 金鑰（到 https://aistudio.google.com/apikey 申請）
export GEMINI_API_KEY="your_api_key_here"      # Windows: set GEMINI_API_KEY=...

# 3. 一鍵執行
python annotate.py
```

執行後產生 `annotated_results.json`，並在終端印出各標籤分佈統計。

先試跑小量再全量：

```bash
python annotate.py --limit 30                  # 只跑前 30 筆
python annotate.py --model gemini-2.5-pro      # 換更強的模型
```

---

## 資料格式

輸入 `data/extracted_data_with_id.json`：物件陣列（共 1000 筆，id 10001–11000），每筆含 `id` 與 `data`（一段繁體中文 ESG 報告內文）。

```json
{ "id": "10001", "data": "聯發科技除在「工作規則」中依照勞基法…" }
```

---

## 標註結構

| 欄位 | 允許值 | 說明 |
|------|--------|------|
| `promise_status` | `Yes` / `No` | 段落是否包含 ESG 承諾（原則、承諾、策略） |
| `promise_string` | 字串 | 逐字擷取的承諾；多片段以「 ｜ 」串接；無承諾為 `""` |
| `verification_timeline` | 見下 | 承諾預期完成／可驗證時程 |
| `evidence_status` | `Yes` / `No` / `N/A` | 是否有支持承諾的證據 |
| `evidence_string` | 字串 | 逐字擷取的證據；多片段以「 ｜ 」串接；無證據為 `""` |
| `evidence_quality` | `Clear` / `Not Clear` / `Misleading` / `N/A` | 證據與承諾之關聯品質 |

**`verification_timeline`（以報告書公開年份 2024 起算）**

| 值 | 定義 |
|----|------|
| `already` | 已實行，可於當期驗證 |
| `within_2_years` | 短期，2 年內可驗證 |
| `between_2_and_5_years` | 中長期，2–5 年可驗證；**未明示目標完成年份時亦選此** |
| `more_than_5_years` | 長期，5 年以上可驗證 |
| `N/A` | **僅在** `promise_status` 為 `No` 時使用 |

> 規則：`promise_status` 為 `Yes` 時，`verification_timeline` 不得為 `N/A`。

**多片段擷取**：當承諾或證據由文中多個不連續片段組成時，各片段逐字擷取後以全形分隔符「 ｜ 」（前後各一空格）串接。

---

## 輸出格式

單一 JSON 陣列，每筆保留原始 `id` 與 `data`，key 順序固定為
`id` → `data` → `promise_status` → `promise_string` → `verification_timeline` → `evidence_status` → `evidence_string` → `evidence_quality`。

```json
{
  "id": "11001",
  "data": "為有效預防控制職業危害，公司制訂有「職業病控制管理規定」。…完善安全操作規範。",
  "promise_status": "Yes",
  "promise_string": "為有效預防控制職業危害，公司制訂有「職業病控制管理規定」。 ｜ 對於職業傷害，公司均落實改善措施，",
  "verification_timeline": "already",
  "evidence_status": "Yes",
  "evidence_string": "公司對所涉及的職業病危害項目由營運服務部向政府部門進行申報… ｜ 包括：增設設備安全防護…完善安全操作規範。",
  "evidence_quality": "Clear"
}
```

---

## 特性

- **一鍵全流程**：`python annotate.py` 完成讀取、標註、存檔、統計。
- **Schema 強制輸出**：以 `response_schema`（Pydantic）確保每筆欄位與允許值正確。
- **斷點續跑**：每筆完成即寫檔，中斷後重跑自動略過已完成 id。
- **單筆錯誤不中斷**：失敗筆記錄 `error` 欄位，重跑即補做。
- **統計摘要**：結束時列出 promise / timeline / evidence 各類別分佈與錯誤數。

### 指令參數

| 參數 | 預設 | 說明 |
|------|------|------|
| `--input` | `data/extracted_data_with_id.json` | 輸入路徑 |
| `--output` | `annotated_results.json` | 輸出路徑 |
| `--model` | `gemini-2.5-flash` | 模型（另可 `gemini-2.5-pro` / `gemini-3.1-pro`） |
| `--limit` | 無 | 只處理前 N 筆（試跑） |
| `--sleep` | `0` | 每筆間隔秒數（遇 rate limit 可調大） |

---

## 檔案結構

```
esg-annotation/
├── annotate.py        # 一鍵標註主程式（方式 B：API 全量）
├── prompt.txt         # 網頁版 prompt（方式 A：Gemini 網頁上傳貼上用）
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
└── data/
    └── extracted_data_with_id.json    # 輸入資料
```

## 兩種執行方式

- **方式 B（建議）**：如上 Quick Start，適合完整 1000 筆正式標註。
- **方式 A（快速測試）**：將 `data/extracted_data_with_id.json` 上傳至 Gemini 網頁，貼上 `prompt.txt` 全文送出。適合驗證 prompt 效果；一次處理大量時網頁常會中途截斷，正式標註請用方式 B。

---

