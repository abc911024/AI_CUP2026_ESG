# ESG 承諾與證據標註工作流程（ESG Promise & Evidence Annotation）

本專案使用大型語言模型（Gemini）自動標註繁體中文企業永續報告書段落，抽取其中的 ESG 承諾（promise）與對應證據（evidence），並判斷驗證時程與證據品質。

---

## 1. 資料格式（Input）

輸入為單一 JSON 檔 `extracted_data_with_id.json`，內容是一個物件陣列，共 1000 筆（id 範圍 10001–11000），每筆包含兩個欄位：

| 欄位 | 說明 |
|------|------|
| `id` | 段落唯一識別碼（字串） |
| `data` | 一段繁體中文的企業 ESG 報告內文 |

範例：

```json
{
  "id": "10001",
  "data": "聯發科技除在「工作規則」中依照勞基法明確規定…陪產（檢）假期間工資照常給付。"
}
```

---

## 2. 標註結構（Annotation Schema）

每筆段落輸出六個標註欄位，加上原始的 `id` 與 `data`，共八個欄位。

| 欄位 | 型別 / 允許值 | 說明 |
|------|--------------|------|
| `promise_status` | `Yes` / `No` | 段落是否包含 ESG 承諾（原則、承諾或策略） |
| `promise_string` | 字串 | 逐字擷取的承諾原文；無承諾時為 `""` |
| `verification_timeline` | 見下表 | 承諾預期完成／可驗證的時程 |
| `evidence_status` | `Yes` / `No` / `N/A` | 是否有支持承諾的證據；無承諾時為 `N/A` |
| `evidence_string` | 字串 | 逐字擷取的證據原文；無證據時為 `""` |
| `evidence_quality` | `Clear` / `Not Clear` / `Misleading` / `N/A` | 證據與承諾之關聯品質 |

### 2.1 `verification_timeline` 類別（以報告書公開年份 2024 起算）

| 值 | 定義 |
|----|------|
| `already` | 承諾已實行，可於當期驗證 |
| `within_2_years` | 短期規劃，2 年內可驗證 |
| `between_2_and_5_years` | 中長期規劃，2–5 年可驗證；**承諾未明示目標完成年份時亦選此項** |
| `more_than_5_years` | 長期規劃，5 年以上可驗證 |
| `N/A` | **僅在** `promise_status` 為 `No` 時使用 |

> 規則：`promise_status` 為 `Yes` 時，`verification_timeline` 不得為 `N/A`。

### 2.2 多片段擷取規則

當承諾或證據由文中**多個不連續片段**組成時，各片段逐字擷取後，以全形分隔符「` ｜ `」（前後各一空格）串接。例如：

```
"promise_string": "為有效預防控制職業危害，公司制訂有「職業病控制管理規定」。 ｜ 對於職業傷害，公司均落實改善措施，"
```

---

## 3. 輸出格式（Output）

輸出為單一 JSON 陣列，每筆保留原始 `id` 與 `data`，並依固定順序附上六個標註欄位：

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

Key 順序固定為：`id` → `data` → `promise_status` → `promise_string` → `verification_timeline` → `evidence_status` → `evidence_string` → `evidence_quality`。

---

## 4. 執行方式

### Gemini API 腳本

逐筆呼叫 API，並以 `response_schema` 強制結構化輸出。

```bash
pip install google-genai pydantic
export GEMINI_API_KEY="你的key"        # Windows: set GEMINI_API_KEY=...
python annotate_esg_gemini.py
```

腳本特性：

- 逐筆讀取輸入、逐筆呼叫，每筆獨立套用 schema，確保欄位與允許值正確。
- 斷點續跑：每筆完成即寫入 `annotated_results.json`，中途中斷後重跑會自動略過已完成的 id。
- 單筆錯誤不中斷整批：失敗筆會記錄 `error` 欄位，重跑即補做。

模型選擇：1000 筆建議 `gemini-2.5-flash`（快、成本低）；需更精細判斷（尤其 `evidence_quality`）可改用 `gemini-2.5-pro` 或 `gemini-3.1-pro`。


---

## 5. 檔案清單

| 檔案 | 用途 |
|------|------|
| `extracted_data_with_id.json` | 輸入資料（1000 筆待標註段落） |
| `prompt.txt` | 標註用 prompt（方式 A 貼上；方式 B 內嵌於腳本） |
| `annotate_esg_gemini.py` | Gemini API 批次標註腳本（方式 B） |
| `annotated_results.json` | 輸出結果 |

---

## 6. 品質建議

- 目前 few-shot 範例已涵蓋 `already`、`within_2_years`、`more_than_5_years`、`Clear`、`Not Clear` 等情況。若正式跑後發現 `between_2_and_5_years`、`No`（無承諾）、`Misleading` 判別不準，補一兩個對應範例通常能明顯改善。
- 正式全量前，建議先抽 30–50 筆人工核對標註一致性，再放大跑完整資料集。
