# test_controller.py
# 用途：最小化测试 controller 的最终输出（不跑任何 demo/fallback）
# 位置：与 runtime/ 同级；已假设 runtime/.cache/compiled.json 存在且结构正确

from __future__ import annotations
from pathlib import Path
import sys
import json
import argparse

# 让 `python test_controller.py` 能找到 runtime 包
HERE = Path(__file__).resolve().parent
ROOT = HERE  # runtime/ 与本脚本同级
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.controller import run_once  # noqa: E402

def pretty_print_result(user_text: str, result: dict) -> None:
    router = result.get("router", {})
    retr   = result.get("retriever", {})
    emo    = result.get("emotion", {})

    print("=" * 60)
    print("USER:", user_text)
    print("[slot]", result.get("slot"), "| route_conf:", router.get("route_confidence"))
    print("[must]", router.get("must"), "| [forbid]:", router.get("forbid"))
    flags = (retr or {}).get("flags") or {}
    ev    = (retr or {}).get("evidence") or []
    print("[retriever.flags]", flags)
    print(f"[evidence] {len(ev)} item(s)")
    if ev:
        # 只预览前两条
        preview = [{"fact_id": e.get("fact_id"), "entity": e.get("entity"), "fact": e.get("fact")} for e in ev[:2]]
        print("[evidence.preview]", json.dumps(preview, ensure_ascii=False))
    print("[draft]", result.get("draft"))
    print("[emotion.final]", (emo or {}).get("final"), "| style:", (emo or {}).get("style"))

def main():
    parser = argparse.ArgumentParser(description="Smoke test for runtime.controller (strict, compiled.json only).")
    parser.add_argument("texts", nargs="*", help="User inputs to test (defaults to a small set).")
    parser.add_argument("--npc", default=None, help="Optional NPC id.")
    parser.add_argument("--json", action="store_true", help="Print raw JSON results after pretty output.")
    args = parser.parse_args()

    tests = args.texts or [
        "what's new in the market?",
        "any news from the marketplace guild?",
        "tell me about patrol shifts near the east gate",
        "hi there, how's your day?",
        "where's the black market tonight?",
    ]

    for t in tests:
        try:
            res = run_once(t, npc_id=args.npc)
            pretty_print_result(t, res)
            if args.json:
                print("--- RAW JSON ---")
                print(json.dumps(res, ensure_ascii=False, indent=2))
        except Exception as e:
            print("=" * 60)
            print("USER:", t)
            print("[ERROR]", e)

if __name__ == "__main__":
    main()
