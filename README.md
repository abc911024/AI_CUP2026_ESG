# ESG 承諾與證據標註（ESG Promise & Evidence Annotation）

**AI CUP 2026 VeriPromiseESG** 競賽標註流程：自動標註繁體中文企業永續報告書段落，抽取 **ESG 承諾（promise）** 與 **對應證據（evidence）**，並判斷 **驗證時程** 與 **證據品質**。

採 **兩階段（RAG → LLM）** 設計，皆已實作為可執行程式：

1. **階段 1 — RAG 檢索**（`retrieve.py`）：以 Multilingual E5 編碼，FAISS 為每筆**待標段落（test 集）** 檢索最相似的「已標註範例（train 集）」。
2. **階段 2 — LLM 標註**（`annotate.py`）：把檢索到的範例當動態 few-shot，交由 Gemini（`response_schema` 強制結構化輸出）產生標註，並輸出**競賽提交格式 CSV**。


---

## 工作流程總覽

```
vpesg4k_test_2000.csv (待標)        vpesg4k_train_1000.json (已標註語料)
        │                                    │
        │                                    ▼
        │                        Multilingual E5 編碼 → FAISS 索引
        │                                    │
        ▼                                    │
    E5 編碼 ───────────► 檢索 top-k 相似範例 ◄┘   ← 階段 1 (retrieve.py)
                            │
                            ▼
             data/retrieved_examples.json  (每筆 query 的動態 few-shot)
                            │
                            ▼
        Gemini（response_schema 強制）產生標註       ← 階段 2 (annotate.py)
                            │
              ┌─────────────┴─────────────┐
              ▼                           ▼
   annotated_results.json          submission.csv
   (完整，含 data 與 string)        (競賽提交格式，5 欄)
```

---

## Quick Start

```bash
# 1. 安裝相依套件（含 E5 / FAISS / Gemini SDK）
pip install -r requirements.txt

# 2. 設定 API 金鑰（到 https://aistudio.google.com/apikey 申請）
export GEMINI_API_KEY="your_api_key_here"      # Windows: set GEMINI_API_KEY=...

# 3. 一鍵跑完整流程（階段 1 → 階段 2）
python run_all.py
```
---

## 資料

放入 `data/`（見 `data/README.md`）：

| 檔案 | 角色 | 說明 |
|------|------|------|
| `vpesg4k_test_2000.csv` | 待標目標 | 2000 筆，id 12001–，欄位含 `id, data, company, …` |
| `vpesg4k_train_1000.json` | RAG 語料 | 1000 筆已標註，含全部標籤欄位 |
| `vpesg4k_val_1000.json` | 額外語料（可選） | 以 `--corpus` 多檔加入 |
| `sample_submission_format.csv` | 格式對照 | 提交欄位範例 |

---

## 階段 1：RAG 檢索（retrieve.py）

以 Multilingual E5 編碼 corpus 與 queries，FAISS（cosine）檢索每筆 query 的 top-k 相似範例。輸出 `data/retrieved_examples.json`：`{ query_id: [ { text, labels, score }, … ] }`，並自動排除「檢索到自己」。queries 與 corpus 皆支援 `.json` / `.csv`。

| 參數 | 預設 | 說明 |
|------|------|------|
| `--queries` | `data/vpesg4k_test_2000.csv` | 待標段落 |
| `--corpus` | `data/vpesg4k_train_1000.json` | 已標註語料（可多檔） |
| `--out` | `data/retrieved_examples.json` | 檢索結果輸出 |
| `--text-field` | `data` | 文字欄位 |
| `--top-k` | `６` | 每筆檢索範例數 |
| `--model` | `intfloat/multilingual-e5-large` | E5 模型 |
| `--batch-size` | `32` | 編碼 batch size |

---

## 階段 2：LLM 標註（annotate.py）

為每筆組動態 few-shot，呼叫 Gemini 產生結構化標註；每筆即時存檔、支援斷點續跑與統計，並輸出提交 CSV。

| 參數 | 預設 | 說明 |
|------|------|------|
| `--input` | `data/vpesg4k_test_2000.csv` | 待標段落（.json / .csv） |
| `--retrieved` | `data/retrieved_examples.json` | 階段 1 檢索結果（缺檔則用固定 few-shot） |
| `--output` | `annotated_results.json` | 完整標註（JSON） |
| `--submission` | `submission.csv` | 競賽提交檔（CSV） |
| `--model` | `gemini-2.5-flash` | 模型（另可 `gemini-2.5-pro` / `gemini-3.1-pro`） |
| `--limit` | 無 | 只處理前 N 筆（試跑） |
| `--sleep` | `0` | 每筆間隔秒數（遇 rate limit 可調大） |

---

## 標註結構

| 欄位 | 允許值 | 說明 |
|------|--------|------|
| `promise_status` | `Yes` / `No` | 段落是否包含 ESG 承諾 |
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

**多片段擷取**：承諾或證據由多個不連續片段組成時，各片段逐字擷取後以全形分隔符「 ｜ 」（前後各一空格）串接。

---

## 輸出

- **`submission.csv`（提交用）**：5 欄 `id, promise_status, verification_timeline, evidence_status, evidence_quality`，依 id 排序、無 BOM，對齊 `sample_submission_format.csv`。
- **`annotated_results.json`（檢查用）**：保留 `id`、`data` 與 promise/evidence 原文，key 順序 `id` → `data` → 六個標註欄位。

---

## 特性

- **完整兩階段流程**：`run_all.py` 一鍵串起 RAG 檢索與 LLM 標註。
- **動態 few-shot**：每筆使用檢索到的相似範例；缺檢索結果時自動退回固定範例。
- **Schema 強制輸出**：以 `response_schema`（Pydantic）確保欄位與允許值正確。
- **斷點續跑**：每筆完成即寫檔，中斷後重跑自動略過已完成 id。
- **單筆錯誤不中斷**：失敗筆記錄 `error`，提交檔以保守值 `No/N/A` 填補，重跑即補做。
- **雙輸出**：同時產生提交 CSV 與可檢查的完整 JSON。

---

## 檔案結構

```
AI_CUP2026_ESG/
├── run_all.py          # 一鍵：階段 1 → 階段 2
├── retrieve.py         # 階段 1：RAG 檢索（E5 + FAISS）
├── annotate.py         # 階段 2：LLM 標註（Gemini，動態 few-shot）+ 提交 CSV
├── io_utils.py         # 共用：讀 JSON/CSV、寫提交 CSV
├── prompt.txt          # 網頁版 prompt（Gemini 網頁上傳貼上用）
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── AI_CUP_2026_VeriPromiseESG_Submission_Guidelines.pdf  # 競賽規則
└── data/
    ├── README.md                      # 說明應放入哪些資料
    ├── vpesg4k_test_2000.csv          # 待標段落（2000 筆，id 12001–）
    ├── vpesg4k_train_1000.json/.csv   # 訓練集（RAG 檢索語料）
    ├── vpesg4k_val_1000.json/.csv     # 驗證集
    └── sample_submission_format.csv   # 提交格式範例
```

---
