#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
階段 2：ESG 承諾與證據標註（Gemini）
=================================================
讀取輸入（JSON/CSV）-> 逐筆呼叫 Gemini（schema 強制結構化輸出，
若有階段 1 retrieve.py 產生的檢索結果則當動態 few-shot）
-> 存成完整結果 JSON + 競賽提交 CSV -> 印出統計摘要。

用法：
    python retrieve.py                                  # 階段 1：先產生 data/retrieved_examples.json
    python annotate.py                                  # 階段 2：標註 + 產生 submission.csv
    python annotate.py --model gemini-2.5-pro
    python annotate.py --limit 30                        # 先試跑前 30 筆
"""

import argparse
import csv
import json
import os
import sys
import time
from collections import Counter
from typing import Literal

from google import genai
from pydantic import BaseModel

SUBMISSION_FIELDS = [
    "id", "promise_status", "verification_timeline", "evidence_status", "evidence_quality",
]


# ============================================================
# 輸出結構（schema：Gemini 會被強制只回這些欄位、值落在允許範圍）
# ============================================================
class Annotation(BaseModel):
    promise_status: Literal["Yes", "No"]
    promise_string: str
    verification_timeline: Literal[
        "already",
        "within_2_years",
        "between_2_and_5_years",
        "more_than_5_years",
        "N/A",
    ]
    evidence_status: Literal["Yes", "No", "N/A"]
    evidence_string: str
    evidence_quality: Literal["Clear", "Not Clear", "Misleading", "N/A"]


# ============================================================
# 任務說明（固定）+ few-shot 範例（動態：來自 retrieve.py 檢索結果；
# 若某筆查無檢索結果則退回下方固定範例）
# ============================================================
TASK_INSTRUCTIONS = """You are an expert in extracting ESG-related promises and their corresponding evidence from corporate reports.

Analyze the given Traditional Chinese paragraph from a corporate ESG report and produce the annotation.

Labels:
- promise_status: "Yes" if the paragraph contains an ESG-related promise (a principle, commitment, or strategy), otherwise "No".
- promise_string: the exact wording of the promise, copied verbatim (use "" if no promise). If the promise consists of MULTIPLE non-contiguous fragments, copy each fragment verbatim and join them with " ｜ " (a full-width vertical bar surrounded by single spaces).
- verification_timeline: Based on the meaning of the text, infer the expected completion time of the promise, counting from the year 2024 (the report publication year). Choose exactly ONE:
    - "already": already implemented and verifiable in the current period.
    - "within_2_years": short-term plan, verifiable within 2 years.
    - "between_2_and_5_years": medium-to-long-term plan, verifiable within 2 to 5 years. ALSO use this when the promise does not explicitly state a target completion year.
    - "more_than_5_years": long-term plan, verifiable after more than 5 years.
    - "N/A": use ONLY when promise_status is "No".
  If promise_status is "Yes", verification_timeline must NEVER be "N/A".
- evidence_status: "Yes" if evidence supports the promise, "No" if not, "N/A" if no promise.
- evidence_string: the supporting evidence, copied verbatim (use "" if none). If multiple non-contiguous fragments, join them with " ｜ ".
- evidence_quality: "Clear" (sufficient and logical) / "Not Clear" (partial or superficial) / "Misleading" (unrelated, diverts attention) / "N/A"."""

FIXED_EXAMPLES = """[Example 1]
統一超商積極透過推動綠色採購管理設備、耗材與建材，選擇綠建材進行門市裝修並採購取得節能標章、環保標章或驗證或具有實際環保效益的設備與耗材應用於門市
-> promise_status: Yes | promise_string: "統一超商積極透過推動綠色採購管理設備、耗材與建材" | verification_timeline: within_2_years | evidence_status: Yes | evidence_string: "選擇綠建材進行門市裝修並採購取得節能標章、環保標章或驗證或具有實際環保效益的設備與耗材應用於門市" | evidence_quality: Clear

[Example 2]
和碩由董事長童子賢先生公開宣誓集團對長期節能減碳的決心…企總及各主要製造廠區皆成立溫室氣體盤查委員會…進一步擬定減量計畫及設定減量目標。
-> promise_status: Yes | promise_string: "和碩由董事長童子賢先生公開宣誓集團對長期節能減碳的決心，期能在集團的共同努力下，對全球溫室氣體減量能有所貢獻" | verification_timeline: more_than_5_years | evidence_status: Yes | evidence_string: "企總及各主要製造廠區皆成立溫室氣體盤查委員會，進行溫室氣體盤查與管理，釐清轄屬的溫室氣體排放源，以此為依據進一步擬定減量計畫及設定減量目標" | evidence_quality: Clear

[Example 3]
為響應主管機關推動職場不法侵害預防，公司透過跨單位合作，逐項檢視各項執行作為，設定短、中、長期執行目標…相關執行作為如下：
-> promise_status: Yes | promise_string: "公司透過跨單位合作，逐項檢視各項執行作為，設定短、中、長期執行目標，從軟體到硬體，進行檢視、補強與強化，增加安全保護機制營造友善職場" | verification_timeline: more_than_5_years | evidence_status: Yes | evidence_string: "公司透過跨單位合作，逐項檢視各項執行作為，設定短、中、長期執行目標，從軟體到硬體，進行檢視、補強與強化，增加安全保護機制" | evidence_quality: Not Clear

[Example 4 — joining multiple non-contiguous fragments with " ｜ "]
為有效預防控制職業危害，公司制訂有「職業病控制管理規定」。公司對所涉及的職業病危害項目由營運服務部向政府部門進行申報…對於職業傷害，公司均落實改善措施，包括：增設設備安全防護，嚴格落實設備點檢與保養，加強安全教育培訓，管理人員高頻巡檢，完善安全操作規範。
-> promise_status: Yes | promise_string: "為有效預防控制職業危害，公司制訂有「職業病控制管理規定」。 ｜ 對於職業傷害，公司均落實改善措施，" | verification_timeline: already | evidence_status: Yes | evidence_string: "公司對所涉及的職業病危害項目由營運服務部向政府部門進行申報，由有資質的技術服務機構提供評價工作，並獲得相關部門的驗收批復。根據危險辨識與控制內容對從事接觸職業病危害因素工作的員工進行職業培訓及崗前、崗中、崗後職業健康檢查。 ｜ 包括：增設設備安全防護，嚴格落實設備點檢與保養，加強安全教育培訓，管理人員高頻巡檢，完善安全操作規範。" | evidence_quality: Clear"""


def load_rows(path: str) -> list:
    """讀輸入資料，依副檔名判斷 JSON 或 CSV，回傳 list[dict]（至少含 id、data）。"""
    if path.lower().endswith(".csv"):
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_examples_block(retrieved: list) -> str:
    """把 retrieve.py 檢索到的範例組成 few-shot 文字區塊。"""
    lines = []
    for i, ex in enumerate(retrieved, 1):
        lines.append(f"[Example {i}]\n{ex.get('text', '')}\n-> {ex.get('labels', '')}")
    return "\n\n".join(lines)


def build_prompt(paragraph: str, retrieved: list) -> str:
    examples = build_examples_block(retrieved) if retrieved else FIXED_EXAMPLES
    return (
        f"{TASK_INSTRUCTIONS}\n\n"
        f"Reference examples (paragraph -> labels):\n\n{examples}\n\n"
        f"Now analyze the following paragraph:\n\n{paragraph}"
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Stage 2: LLM annotation (Gemini), with optional RAG few-shot.")
    p.add_argument("--input", default="data/vpesg4k_test_2000.csv", help="待標段落（.json / .csv）")
    p.add_argument("--retrieved", default="data/retrieved_examples.json",
                   help="階段 1 retrieve.py 的檢索結果（缺檔則用固定 few-shot）")
    p.add_argument("--output", default="annotated_results.json", help="完整標註輸出（JSON）")
    p.add_argument("--submission", default="submission.csv", help="競賽提交檔輸出（CSV）")
    p.add_argument("--model", default="gemini-2.5-flash",
                   help="Gemini 模型（gemini-2.5-flash / gemini-2.5-pro / gemini-3.1-pro）")
    p.add_argument("--limit", type=int, default=None, help="只處理前 N 筆（試跑用）")
    p.add_argument("--sleep", type=float, default=0.0, help="每筆間隔秒數（遇 rate limit 可調大）")
    return p.parse_args()


def annotate_one(client: genai.Client, model: str, paragraph: str, retrieved: list) -> dict:
    response = client.models.generate_content(
        model=model,
        contents=build_prompt(paragraph, retrieved),
        config={
            "response_mime_type": "application/json",
            "response_schema": Annotation,
        },
    )
    if response.parsed:
        return response.parsed.model_dump()
    return json.loads(response.text)


def write_submission(path: str, results: list) -> None:
    rows = sorted(results, key=lambda r: str(r["id"]))
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SUBMISSION_FIELDS)
        writer.writeheader()
        for r in rows:
            if "error" in r:
                # 失敗筆以保守值填補，確保提交檔涵蓋所有 id
                writer.writerow({"id": r["id"], "promise_status": "No", "verification_timeline": "N/A",
                                  "evidence_status": "N/A", "evidence_quality": "N/A"})
            else:
                writer.writerow({k: r.get(k, "") for k in SUBMISSION_FIELDS})


def print_stats(results: list) -> None:
    print("\n" + "=" * 48)
    print(f"總筆數：{len(results)}")
    errors = [r for r in results if "error" in r]
    print(f"錯誤筆數：{len(errors)}")
    ok = [r for r in results if "error" not in r]
    for field in ("promise_status", "verification_timeline", "evidence_status", "evidence_quality"):
        counts = Counter(r.get(field, "?") for r in ok)
        dist = "  ".join(f"{k}={v}" for k, v in counts.most_common())
        print(f"{field:22s}: {dist}")
    print("=" * 48)


def main() -> None:
    args = parse_args()

    if not os.path.exists(args.input):
        sys.exit(f"找不到輸入檔：{args.input}")

    data = load_rows(args.input)
    if args.limit:
        data = data[: args.limit]

    retrieved_map: dict = {}
    if os.path.exists(args.retrieved):
        with open(args.retrieved, "r", encoding="utf-8") as f:
            retrieved_map = json.load(f)
        print(f"已載入檢索結果 {args.retrieved}，將用動態 few-shot。")
    else:
        print(f"[提示] 找不到 {args.retrieved}，改用固定 few-shot（可先跑 python retrieve.py 產生）。")

    # 斷點續跑：載入既有結果
    results: dict[str, dict] = {}
    if os.path.exists(args.output):
        with open(args.output, "r", encoding="utf-8") as f:
            for item in json.load(f):
                results[item["id"]] = item
        print(f"已載入 {len(results)} 筆既有結果，將略過這些 id。")

    client = genai.Client()  # 讀取 GEMINI_API_KEY / GOOGLE_API_KEY 環境變數
    total = len(data)

    for i, row in enumerate(data, 1):
        rid = row["id"]
        if rid in results:
            continue
        try:
            ann = annotate_one(client, args.model, row["data"], retrieved_map.get(str(rid), []))
            # 固定 key 順序：id -> data -> 六個標註欄位
            results[rid] = {"id": rid, "data": row["data"], **ann}
            print(f"[{i}/{total}] id={rid}  promise={ann.get('promise_status')}  "
                  f"timeline={ann.get('verification_timeline')}")
        except Exception as e:
            results[rid] = {"id": rid, "data": row["data"], "error": str(e)}
            print(f"[{i}/{total}] id={rid}  ERROR: {e}", file=sys.stderr)

        # 每筆即時存檔，確保中斷不丟進度
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(list(results.values()), f, ensure_ascii=False, indent=2)
        write_submission(args.submission, list(results.values()))

        if args.sleep:
            time.sleep(args.sleep)

    print(f"\n完成，結果寫入 {args.output}、提交檔寫入 {args.submission}")
    print_stats(list(results.values()))


if __name__ == "__main__":
    main()
