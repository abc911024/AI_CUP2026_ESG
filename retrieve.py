#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
階段 1：RAG 檢索
================
用 Multilingual E5 將「已標註範例庫（corpus）」與「待標段落（queries）」編碼，
以 FAISS（cosine）為每筆 query 檢索 top-k 最相似的已標註範例，
輸出 data/retrieved_examples.json 供階段 2（annotate.py）當動態 few-shot。

用法：
    python retrieve.py
    python retrieve.py --corpus data/vpesg4k_train_1000.json --top-k 5
    python retrieve.py --queries data/vpesg4k_test_2000.json --out data/retrieved_test.json
"""

import argparse
import csv
import json
import os
import sys

import numpy as np

# 標註標籤欄位（若 corpus 內含這些欄位，會一併組成 few-shot 的「答案」）
LABEL_FIELDS = [
    "promise_status", "promise_string", "verification_timeline",
    "evidence_status", "evidence_string", "evidence_quality",
]


def load_rows(path: str) -> list:
    """讀 corpus/queries，依副檔名判斷 JSON 或 CSV，回傳 list[dict]。"""
    if path.lower().endswith(".csv"):
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        sys.exit(f"{path} 不是 JSON 陣列")
    return data


def format_labels(item: dict) -> str:
    """把 corpus 一筆的標籤欄位組成 few-shot 的答案字串（只取存在的欄位）。"""
    parts = []
    for k in LABEL_FIELDS:
        if k in item and item[k] not in (None, ""):
            v = item[k]
            parts.append(f'{k}: "{v}"' if k.endswith("_string") else f"{k}: {v}")
    return " | ".join(parts)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Stage 1: RAG retrieval (E5 + FAISS).")
    p.add_argument("--queries", default="data/vpesg4k_test_2000.csv",
                   help="待標段落（.json / .csv，需含 id 與文字欄位）")
    p.add_argument("--corpus", nargs="+", default=["data/vpesg4k_train_1000.json"],
                   help="已標註範例庫（.json / .csv，可多個檔）")
    p.add_argument("--out", default="data/retrieved_examples.json", help="檢索結果輸出路徑")
    p.add_argument("--text-field", default="data", help="文字欄位名稱")
    p.add_argument("--id-field", default="id", help="id 欄位名稱")
    p.add_argument("--top-k", type=int, default=3, help="每筆 query 檢索的範例數")
    p.add_argument("--model", default="intfloat/multilingual-e5-large", help="E5 模型")
    p.add_argument("--batch-size", type=int, default=32, help="編碼 batch size")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    # 延遲載入重套件，讓 --help 等不必先裝 torch
    import faiss
    from sentence_transformers import SentenceTransformer

    if not os.path.exists(args.queries):
        sys.exit(f"找不到 queries：{args.queries}")

    # 載入 corpus（可多檔合併）
    corpus = []
    for c in args.corpus:
        if not os.path.exists(c):
            print(f"[警告] corpus 檔不存在，略過：{c}", file=sys.stderr)
            continue
        corpus.extend(load_rows(c))
    if not corpus:
        sys.exit("corpus 為空，請確認 --corpus 路徑（應為已標註範例庫）")

    queries = load_rows(args.queries)
    tf, idf = args.text_field, args.id_field

    print(f"corpus {len(corpus)} 筆、queries {len(queries)} 筆，載入模型 {args.model} …")
    model = SentenceTransformer(args.model)

    # E5 慣例：corpus 前綴 "passage: "、query 前綴 "query: "
    corpus_texts = [f"passage: {it.get(tf, '')}" for it in corpus]
    query_texts = [f"query: {q.get(tf, '')}" for q in queries]

    corpus_emb = model.encode(corpus_texts, normalize_embeddings=True,
                              batch_size=args.batch_size, show_progress_bar=True)
    query_emb = model.encode(query_texts, normalize_embeddings=True,
                             batch_size=args.batch_size, show_progress_bar=True)
    corpus_emb = np.asarray(corpus_emb, dtype="float32")
    query_emb = np.asarray(query_emb, dtype="float32")

    # normalize 後用內積 = cosine similarity
    index = faiss.IndexFlatIP(corpus_emb.shape[1])
    index.add(corpus_emb)

    # 多取一些，之後過濾掉「檢索到自己」再截成 top-k
    over_k = args.top_k + 5
    sims, idxs = index.search(query_emb, min(over_k, len(corpus)))

    result = {}
    for qi, q in enumerate(queries):
        qid = str(q.get(idf, qi))
        neighbors = []
        for rank, ci in enumerate(idxs[qi]):
            if ci < 0:
                continue
            cand = corpus[ci]
            # 避免把 query 自己當範例（同 id 或同文字）
            if str(cand.get(idf)) == qid or cand.get(tf) == q.get(tf):
                continue
            neighbors.append({
                "text": cand.get(tf, ""),
                "labels": format_labels(cand),
                "score": float(sims[qi][rank]),
            })
            if len(neighbors) >= args.top_k:
                break
        result[qid] = neighbors

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    avg = sum(len(v) for v in result.values()) / max(len(result), 1)
    print(f"\n完成。每筆平均檢索到 {avg:.1f} 個範例，結果寫入 {args.out}")


if __name__ == "__main__":
    main()
