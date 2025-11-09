# -*- coding: utf-8 -*-
# project/eval/auto_eval.py
# LLM-as-a-Judge 自动化评估工具，用于量化护栏效果与稳定性。
from __future__ import annotations
import argparse, glob, json, os, csv, hashlib, sqlite3, time, sys, pathlib
from typing import Any, Dict, List, Tuple
import statistics
import matplotlib.pyplot as plt  # 假设已安装

# 导入 QwenProvider 和 APIError (兼容路径)
try:
    from project.provider.qwen import QwenProvider, APIError
except Exception:
    THIS = pathlib.Path(__file__).resolve()
    PROJECT_DIR = THIS.parents[1]
    sys.path.insert(0, str(PROJECT_DIR))
    try:
        from provider.qwen import QwenProvider, APIError  # type: ignore
    except Exception:
        class QwenProvider:  # type: ignore
            def __init__(self, *args, **kwargs):
                raise APIError("QwenProvider Import Failed or QWEN_API_KEY missing.")


        class APIError(Exception):
            pass  # type: ignore


# 导入缓存（如果您已实现 project/runtime/cache.py，请替换下面的 KVCache）
class KVCache:
    # 简易 SQLite 缓存实现
    def __init__(self, path="project/eval/.llm_cache.sqlite3"):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        import sqlite3 as _sq
        self.conn = _sq.connect(self.path)
        with self.conn:
            self.conn.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL, ts REAL);")

    def get(self, k: str):
        with self.conn:
            cur = self.conn.execute("SELECT v FROM kv WHERE k=?;", (k,))
            row = cur.fetchone()
            if not row: return None
            try:
                return json.loads(row[0])
            except Exception:
                return None

    def set(self, k: str, v: Any):
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO kv(k, v, ts) VALUES (?, ?, ?);",
                              (_json(k), _json(v), time.time()))


# ---- 辅助函数 (保持不变) ----
def _read_jsonl(globs: List[str]) -> List[Dict[str, Any]]:
    files: List[str] = []
    for pat in globs:
        files.extend(sorted(glob.glob(pat)))
    rows = []
    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line: continue
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        pass
        except FileNotFoundError:
            continue
    return rows


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)


def _sha(s: str) -> str:
    import hashlib as _hl
    return _hl.sha256(s.encode("utf-8")).hexdigest()[:24]


# ----------------- 日志字段解析 (保持不变) -----------------
def _as_dict(x: Any) -> Dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _as_str(x: Any) -> str:
    return x if isinstance(x, str) else ""


def _get_final_text(rec: Dict[str, Any]) -> str:
    f = rec.get("final")
    if isinstance(f, dict): return _as_str(f.get("text"))
    if isinstance(f, str): return f
    return _as_str(rec.get("text"))


def _get_proposed_emotion(rec: Dict[str, Any]) -> str:
    ep = rec.get("emotion_proposed")
    if isinstance(ep, dict): return _as_str(ep.get("emotion"))
    if isinstance(ep, str) and ep.strip(): return ep.strip()
    ph = rec.get("pre_hint")
    if isinstance(ph, dict): return _as_str(ph.get("emotion"))
    if isinstance(ph, str) and ph.strip(): return ph.strip()
    f = rec.get("final")
    if isinstance(f, dict):
        emo = _as_str(f.get("emotion"))
        if emo: return emo
    return ""


def _get_evidence_or_ids(rec: Dict[str, Any]) -> Any:
    if "evidence" in rec: return rec["evidence"]
    if "evidence_ids" in rec: return rec["evidence_ids"]
    return None


def _get_latency(rec: Dict[str, Any]) -> float:
    lat_ms = rec.get("latency_ms")
    if isinstance(lat_ms, (int, float)):
        return float(lat_ms) / 1000.0
    return 0.0


# ----------------- 图表生成工具 (保持不变) -----------------
def _generate_charts(summary: Dict[str, Any], ooc_scores: List[float], leak_flags: List[int], emo_real_flags: List[int],
                     out_dir: str):
    """根据评估结果生成并保存图表。"""
    if plt is None:
        print("⚠️ Matplotlib is not available. Skipping chart generation.", file=sys.stderr)
        return

    os.makedirs(out_dir, exist_ok=True)

    # 1. OOC Risk 分布图 (直方图)
    if ooc_scores:
        plt.figure(figsize=(7, 5))
        plt.hist(ooc_scores, bins=20, range=(0, 1.0), edgecolor='black', alpha=0.7)
        plt.title('Out-of-Character Risk Distribution')
        plt.xlabel('OOC Risk Score (0.0 - 1.0)')
        plt.ylabel('Frequency')
        plt.grid(axis='y', alpha=0.5)
        ooc_path = os.path.join(out_dir, 'ooc_risk_distribution.png')
        plt.savefig(ooc_path)
        plt.close()
        summary['chart_ooc'] = ooc_path
        print(f"✅ OOC Risk Chart saved to: {ooc_path}", file=sys.stderr)

    # 2. 总结指标条形图 (Leak Rate, Emotion Realization Rate)
    labels = []
    values = []

    if leak_flags:
        leak_rate = summary.get('llm_leak_rate', sum(leak_flags) / len(leak_flags) if leak_flags else 0)
        labels.append('Leak Rate')
        values.append(leak_rate)

    if emo_real_flags:
        emo_rate = summary.get('llm_emotion_realization',
                               sum(emo_real_flags) / len(emo_real_flags) if emo_real_flags else 0)
        labels.append('Emotion Realization')
        values.append(emo_rate)

    if labels:
        plt.figure(figsize=(6, 5))
        bars = plt.bar(labels, values, color=['#ff9999', '#66b3ff'])
        plt.ylim(0, 1.05)
        plt.title('Summary Evaluation Metrics')
        plt.ylabel('Rate (0.0 - 1.0)')
        plt.grid(axis='y', alpha=0.5)

        for bar in bars:
            yval = bar.get_height()
            plt.text(bar.get_x() + bar.get_width() / 2, yval + 0.05,
                     f'{yval:.2%}', ha='center', va='bottom')

        summary_path = os.path.join(out_dir, 'summary_metrics_bar.png')
        plt.savefig(summary_path)
        plt.close()
        summary['chart_summary'] = summary_path
        print(f"✅ Summary Metrics Chart saved to: {summary_path}", file=sys.stderr)


# ----------------- 主程序 -----------------
def main():
    ap = argparse.ArgumentParser(description="LLM-as-a-Judge 自动化评估工具，支持多指标量化和 CI/CD 护栏。")

    # 核心输入/输出
    ap.add_argument("--logs", nargs="+", required=True, help="Glob(s) to JSONL logs, e.g. project/logs/npc-*.jsonl")
    ap.add_argument("--forbidden", type=str, default=None, help="forbidden.txt (optional, used for leak judge)")
    ap.add_argument("--out_json", type=str, default="project/eval/auto_eval_summary.json",
                    help="输出汇总 JSON 文件路径.")
    ap.add_argument("--out_csv", type=str, default="project/eval/auto_eval_detailed.csv", help="输出详细 CSV 文件路径.")

    # 新增数据和配置参数 (匹配用户输入)
    ap.add_argument("--bad_examples", type=str, default=None, help="List of bad example responses (optional).")
    ap.add_argument("--special_phrases", type=str, default=None, help="List of phrases that must or must not be used.")

    # LLM 评委选择
    ap.add_argument("--judge", type=str, default="all",
                    choices=["ooc", "leak", "emotion", "consistency", "repetition", "latency", "all"],
                    help="选择要运行的评估指标.")

    # 阈值和 CI/CD 护栏参数 (匹配用户输入)
    ap.add_argument("--ooc_threshold", type=float, default=0.5, help="OOC risk score threshold to trigger CI failure.")
    ap.add_argument("--emotion_consistency_min", type=float, default=0.85,
                    help="Minimum emotion consistency rate required for passing.")
    ap.add_argument("--fail_on_regress", action="store_true", help="如果启用，将对比基线并检测指标是否恶化.")
    ap.add_argument("--fail_on_threshold", action="store_true",
                    help="当 OOC 或 Leak 等核心指标超过阈值时，以非零代码退出.")

    args = ap.parse_args()

    rows = _read_jsonl(args.logs)
    if not rows:
        print(_json({"n_rows": 0}))
        sys.exit(0)

    # 加载敏感词列表
    forbidden_list: List[str] = []
    if args.forbidden and os.path.exists(args.forbidden):
        with open(args.forbidden, "r", encoding="utf-8") as f:
            forbidden_list = [x.strip() for x in f if x.strip()]

    # ❗ 初始化 Provider
    try:
        provider = QwenProvider()
    except APIError as e:
        summary = {"n_rows": len(rows), "errors": len(rows), "fatal_error": str(e)}
        os.makedirs(os.path.dirname(args.out_json), exist_ok=True)
        with open(args.out_json, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(f"致命错误：Provider 初始化失败。{_json(summary)}", file=sys.stderr)
        sys.exit(1)

    cache = KVCache()

    details: List[Dict[str, Any]] = []
    ooc_scores: List[float] = []
    leak_flags: List[int] = []
    emo_real_flags: List[int] = []
    latencies: List[float] = []
    repetition_flags: List[int] = []

    error_count = 0

    for i, r in enumerate(rows):
        # ... (数据提取和 LLM 调用逻辑保持不变，用于 OOC, Leak, Emotion) ...
        rec: Dict[str, Any] = {
            "timestamp": r.get("timestamp"),
            "session_id": r.get("session_id"),
            "turn_id": r.get("turn_id"),
            "slot": r.get("slot"),
            "final_text": _get_final_text(r),
            "proposed_emotion": _get_proposed_emotion(r),
        }

        # 提取延迟 (无需 LLM)
        if args.judge in ("latency", "all"):
            latency_sec = _get_latency(r)
            rec["latency_sec"] = latency_sec
            if latency_sec > 0:
                latencies.append(latency_sec)

        # 提取重复率 (简化版本)
        if args.judge in ("repetition", "all") and i > 0 and details:
            prev_final_text = details[-1].get("final_text", "")
            is_repeated = 1 if rec["final_text"] == prev_final_text and rec["final_text"] else 0
            rec["is_repeated"] = bool(is_repeated)
            repetition_flags.append(is_repeated)

        try:
            final_text = rec["final_text"]
            proposed = rec["proposed_emotion"]
            context = {
                "slot": r.get("slot"),
                "evidence": _get_evidence_or_ids(r),
                "ctx": r.get("ctx"),
            }

            # ---- LLM-as-a-Judge: OOC, Leak, Emotion ----
            # OOC
            if args.judge in ("ooc", "all"):
                key = "ooc:" + _sha(_json(context) + "||" + final_text)
                ooc = cache.get(key)
                if ooc is None:
                    ooc = provider.judge_ooc(context=_json(context), output=final_text)
                    cache.set(key, ooc)
                rec.update({"llm_ooc_risk": float(ooc.get("ooc_risk", 0.0)), "llm_ooc_reasons": ooc.get("reasons", [])})
                ooc_scores.append(float(ooc.get("ooc_risk", 0.0)))

            # Leak
            if args.judge in ("leak", "all"):
                key = "leak:" + _sha(_json(forbidden_list) + "||" + final_text)
                leak = cache.get(key)
                if leak is None:
                    leak = provider.judge_leak(forbidden_list=forbidden_list, output=final_text)
                    cache.set(key, leak)
                leak_flag = 1 if leak.get("leak") else 0
                rec.update({"llm_leak": bool(leak.get("leak", False)), "llm_leak_hits": leak.get("hits", [])})
                leak_flags.append(leak_flag)

            # Emotion Realization
            if args.judge in ("emotion", "all"):
                key = "emo:" + _sha((proposed or "") + "||" + final_text)
                emo = cache.get(key)
                if emo is None:
                    emo = provider.judge_emotion(proposed=proposed or "", output=final_text)
                    cache.set(key, emo)
                realized = bool(emo.get("realized", False))
                rec.update({"llm_emotion_realized": realized, "llm_emotion_evidence": emo.get("evidence", [])})
                emo_real_flags.append(1 if realized else 0)

            # TODO: Future Judge: Consistency/Memory (使用 provider.judge_consistency 等)
            if args.judge in ("consistency", "all"):
                pass

            details.append(rec)

        except APIError as e:
            error_count += 1
            rec.update({"error": f"Qwen API Error: {e}", "raw_sample_truncated": _json(r)[:1000]})
            details.append(rec)
            continue
        except Exception as e:
            error_count += 1
            rec.update({"error": f"{type(e).__name__}: {e}", "raw_sample_truncated": _json(r)[:1000]})
            details.append(rec)
            continue

    # ---- 汇总计算 ----
    summary: Dict[str, Any] = {"n_rows": len(rows), "errors": error_count}

    # 计算各项指标均值
    if ooc_scores: summary["llm_ooc_mean"] = round(sum(ooc_scores) / len(ooc_scores), 4)
    if leak_flags: summary["llm_leak_rate"] = round(sum(leak_flags) / len(leak_flags), 4)
    if emo_real_flags: summary["llm_emotion_realization"] = round(sum(emo_real_flags) / len(emo_real_flags), 4)
    if latencies:
        summary["mean_latency_sec"] = round(statistics.mean(latencies), 4)
        summary["median_latency_sec"] = round(statistics.median(latencies), 4)
    if repetition_flags:
        summary["repetition_rate"] = round(sum(repetition_flags) / (len(rows) - 1), 4) if len(rows) > 1 else 0.0

    # ❗ 生成图表
    chart_output_dir = os.path.join(os.path.dirname(args.out_json), 'charts')
    if details:
        _generate_charts(
            summary=summary,
            ooc_scores=ooc_scores,
            leak_flags=leak_flags,
            emo_real_flags=emo_real_flags,
            out_dir=chart_output_dir
        )

    # 写入 JSON 和 CSV 文件
    os.makedirs(os.path.dirname(args.out_json), exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    os.makedirs(os.path.dirname(args.out_csv), exist_ok=True)
    if details:
        all_keys = set()
        for d in details:
            all_keys.update(d.keys())
        try:
            with open(args.out_csv, "w", encoding="utf-8", newline="") as f_csv:
                writer = csv.DictWriter(f_csv, fieldnames=sorted(list(all_keys)))
                writer.writeheader()
                writer.writerows(details)
        except Exception as e:
            print(f"写入 CSV 文件时发生错误: {e}", file=sys.stderr)

    print(_json(summary))

    # ----------------- CI/CD 阈值告警 (护栏逻辑) -----------------
    if args.fail_on_threshold:
        should_fail = False

        # 1. OOC 阈值检查
        ooc_mean = summary.get("llm_ooc_mean", 0)
        if ooc_mean > args.ooc_threshold:
            print(f"🚨 告警: OOC 风险 ({ooc_mean:.4f}) 超过阈值 {args.ooc_threshold:.2f}.", file=sys.stderr)
            should_fail = True

        # 2. Leak 阈值检查 (硬编码一个默认的 Leak 阈值，因为用户没有在命令行提供)
        LEAK_FAIL_THRESHOLD = 0.05
        leak_rate = summary.get("llm_leak_rate", 0)
        if leak_rate > LEAK_FAIL_THRESHOLD:
            print(f"🚨 告警: 泄密率 ({leak_rate:.4f}) 超过阈值 {LEAK_FAIL_THRESHOLD:.2f}.", file=sys.stderr)
            should_fail = True

        # 3. Emotion Consistency 最小要求检查
        # 警告：此处的 llm_emotion_realization 与 emotion_consistency_min 在语义上略有不同，
        # 但我们使用已实现的 Realization 替代 Consistency 进行检查。
        emo_real = summary.get("llm_emotion_realization", 0)
        if emo_real < args.emotion_consistency_min:
            print(f"🚨 告警: 情感实现率 ({emo_real:.4f}) 低于最低要求 {args.emotion_consistency_min:.2f}.",
                  file=sys.stderr)
            should_fail = True

        # 4. 错误计数检查
        if error_count > 0:
            print(f"🚨 告警: LLM API 调用存在 {error_count} 个错误.", file=sys.stderr)
            should_fail = True

        if should_fail:
            print("❌ 自动评估因阈值失败，退出码 1。", file=sys.stderr)
            sys.exit(1)

    # TODO: 预留给 --fail_on_regress 逻辑
    if args.fail_on_regress:
        # 在此处添加读取基线报告并对比本次 summary 的逻辑
        print("⚠️ fail_on_regress 功能尚未实现对比逻辑。", file=sys.stderr)


if __name__ == "__main__":
    main()