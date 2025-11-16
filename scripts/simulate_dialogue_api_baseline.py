# -*- coding: utf-8 -*-
# scripts/simulate_dialogue_api_baseline.py
#
# 纯 API baseline：
# - 不做检索 / 护栏 / FSM / 情感控制
# - 只把 player_text 丢给 QwenProvider.generate()
# - 结果持续写入 JSONL，供 auto_eval 使用

from __future__ import annotations
import argparse
import csv
import json
import os
import time
from datetime import datetime, timezone

# ⚠️ 假设 QwenProvider 和 APIError 在 project.provider.qwen 中已定义
from project.provider.qwen import QwenProvider, APIError


def now_iso() -> str:
    """返回当前时间的 ISO 8601 格式字符串（UTC）。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_test_cases(path: str):
    """从 CSV 文件加载测试用例。"""
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            # 过滤掉空行
            for row in reader:
                if row:  # 确保行不是空字典
                    rows.append(row)
    except FileNotFoundError:
        print(f"❌ 错误：未找到测试用例文件 → {path}")
        return []
    return rows


def simulate_api_baseline(cases_csv: str, out_logs: str):
    """
    模拟纯 Qwen API baseline 对话生成，并将结果追加写入 JSONL 文件。
    多次运行时，新的结果会直接追加到同一个文件后面，不会覆盖。
    """
    # 初始化 QwenProvider
    provider = QwenProvider()

    # 读取测试用例
    cases = load_test_cases(cases_csv)
    if not cases:
        print("无测试用例，模拟结束。")
        return

    # 确保输出目录存在（如果没有目录部分，就用当前目录）
    log_dir = os.path.dirname(out_logs) or "."
    os.makedirs(log_dir, exist_ok=True)

    # 使用 "a" (append) 模式打开文件，实现持续追加写入
    print(f"✅ 日志将追加写入文件 → {out_logs}")
    fout = open(out_logs, "a", encoding="utf-8")

    total_cases = len(cases)

    for i, row in enumerate(cases):
        # 使用 str() 强制转换为字符串，以避免 NoneType 错误
        npc_id = str(row.get("npc_id", ""))
        session_id = str(row.get("session_id", ""))
        turn_num = str(row.get("turn_num", "1"))
        user_text = str(row.get("player_text", ""))  # 确保 user_text 始终是字符串
        emo = str(row.get("emotion_proposed", "neutral"))

        # 此时 user_text 确保是字符串，可以安全切片
        print(f"[{i + 1}/{total_cases}] Session: {session_id}, Turn: {turn_num} | Player: {user_text[:30]}...")

        final_text = ""
        latency_ms = 0

        try:
            t0 = time.time()
            # 调用 generate（schema=None），让模型“随便说话”
            resp = provider.generate(prompt=user_text, schema=None)
            latency_ms = int((time.time() - t0) * 1000)

            # generate(schema=None) 返回 {'text': '...'}
            if isinstance(resp, dict):
                final_text = resp.get("text", json.dumps(resp, ensure_ascii=False))
            else:
                final_text = str(resp)

        except APIError as e:
            final_text = f"[API ERROR] {e}"
            latency_ms = 0
        except Exception as e:
            # 捕获其他运行时错误
            final_text = f"[RUNTIME ERROR] {e}"
            latency_ms = 0

        rec = {
            "timestamp": now_iso(),
            "session_id": session_id,
            "turn_id": f"{session_id}-turn-{turn_num}",
            "npc_id": npc_id,
            "player_id": "Player",
            "slot": "raw_api",  # 标记这是“纯 API baseline”
            "user_text": user_text,
            "emotion_proposed": emo,

            # 给 auto_eval 用的字段：
            "text": final_text,
            "latency_ms": latency_ms,
        }

        # 持续写入 JSONL（每一行一个 JSON 对象）
        fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
        # 强制将缓冲区内容写入磁盘
        fout.flush()

    fout.close()
    print(f"✔ API baseline 完成，共 {total_cases} 条 → {out_logs}")


def main():
    ap = argparse.ArgumentParser(description="Raw API-only baseline dialogue generator")
    ap.add_argument(
        "--cases_csv",
        type=str,
        default="project/data/test_cases.csv",
        help="测试集 CSV（npc_id,session_id,turn_num,player_text,emotion_proposed）",
    )
    ap.add_argument(
        "--out_logs",
        type=str,
        default="project/logs/baseline_api_run.jsonl",
        help="输出 JSONL 路径（同一个文件多次运行会自动追加，不覆盖）",
    )
    args = ap.parse_args()

    simulate_api_baseline(cases_csv=args.cases_csv, out_logs=args.out_logs)


if __name__ == "__main__":
    main()
