# -*- coding: utf-8 -*-
"""
test_phase2_emotion.py
只测试“阶段2：情绪与风格”（Pre-Hint → Post-Infer），不走任何外部API。
- 若提供 --user_text：跑单条用例
- 若不提供参数：自动跑一组内置测试用例（参考 controller 的 smoke tests 并加量）

运行示例：
    python test_phase2_emotion.py --user_text "What's new in the market?" --npc_id guard_01
    python test_phase2_emotion.py
"""

from __future__ import annotations
import argparse, csv, json, sys
from pathlib import Path
from typing import Dict, Any, Optional, List

# ---------------------------
# 路径解析（健壮，避免重复 runtime/）
# ---------------------------
HERE = Path(__file__).resolve().parent                    # project/runtime
PROJECT_ROOT = HERE.parent                                # project
RUNTIME_DIR = PROJECT_ROOT / "runtime"                    # project/runtime
DATA_DIR = PROJECT_ROOT / "data"                          # project/data
CACHE_FILE = RUNTIME_DIR / ".cache" / "compiled.json"     # project/runtime/.cache/compiled.json
NPC_CSV = DATA_DIR / "npc.csv"

def _find_compiled_json() -> Path:
    candidates = [
        CACHE_FILE,
        HERE / ".cache" / "compiled.json",
        HERE.parent / ".cache" / "compiled.json",
        HERE / "runtime" / ".cache" / "compiled.json",
        PROJECT_ROOT / "runtime" / ".cache" / "compiled.json",
    ]
    for p in candidates:
        if p.exists():
            return p
    # 向上逐级搜寻 runtime/.cache/compiled.json
    cur = HERE
    while cur != cur.parent:
        probe = cur / "runtime" / ".cache" / "compiled.json"
        if probe.exists():
            return probe
        cur = cur.parent
    return CACHE_FILE  # 默认期望位置

# ---------------------------
# 导入项目内模块（与 controller 同源）
# ---------------------------
from qrouter import prepare as route_prepare
from emotion_engine import pre_hint, post_infer

# ---------------------------
# 数据加载
# ---------------------------
def _load_compiled() -> Dict[str, Any]:
    compiled_path = _find_compiled_json()
    if not compiled_path.exists():
        print(f"[ERR] compiled.json not found: {compiled_path}", file=sys.stderr)
        print("请先在项目根目录运行： python compile_data.py", file=sys.stderr)
        sys.exit(2)
    try:
        return json.loads(compiled_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[ERR] failed to read compiled.json: {e}", file=sys.stderr)
        sys.exit(2)

def _try_load_npc_profile(npc_id: str) -> Dict[str, Any]:
    """从 data/npc.csv 读取 NPC 的 baseline_emotion / emotion_range / style_emotion_map / speaking_style。"""
    prof: Dict[str, Any] = {}
    if not NPC_CSV.exists():
        return prof
    try:
        with NPC_CSV.open("r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if str(row.get("npc_id") or "").strip() == str(npc_id):
                    prof["baseline_emotion"] = (row.get("baseline_emotion") or "").strip() or None
                    # emotion_range: JSON 或 "a, b, c"
                    er_raw = (row.get("emotion_range") or "").strip()
                    if er_raw:
                        try:
                            er = json.loads(er_raw)
                            if isinstance(er, list):
                                prof["emotion_range"] = [str(x).strip() for x in er if str(x).strip()]
                        except Exception:
                            parts = [p.strip() for p in er_raw.replace(";", ",").split(",") if p.strip()]
                            prof["emotion_range"] = parts or None
                    # style_emotion_map: JSON 或 "k: v; k2: v2"
                    sem_raw = (row.get("style_emotion_map") or "").strip()
                    if sem_raw:
                        try:
                            sem = json.loads(sem_raw)
                            if isinstance(sem, dict):
                                prof["style_emotion_map"] = sem
                        except Exception:
                            kv = {}
                            sep = ";" if ";" in sem_raw else ","
                            for piece in [p.strip() for p in sem_raw.split(sep) if p.strip()]:
                                if ":" in piece:
                                    k, v = piece.split(":", 1)
                                    kv[k.strip()] = v.strip()
                            if kv:
                                prof["style_emotion_map"] = kv
                    sp = (row.get("speaking_style") or "").strip()
                    if sp:
                        prof["speaking_style"] = sp
                    break
    except Exception:
        pass
    return prof

# ---------------------------
# 阶段2执行
# ---------------------------
def run_phase2_case(user_text: str, npc_id: str, simulated_draft: Optional[str] = None) -> Dict[str, Any]:
    compiled = _load_compiled()
    emo_schema_rt = compiled.get("emotion_schema_runtime") or {}

    # 用路由拿到 slot（与 controller 一致的入口；不改变逻辑）
    router = route_prepare(user_text)
    slot_name = router.get("slot") or "small_talk"

    # NPC profile：从 CSV 覆盖，没有就用安全默认
    npc_profile = {
        "baseline_emotion": "neutral",
        "emotion_range": ["neutral", "friendly", "cheerful", "serious", "annoyed", "sad"],
        "style_emotion_map": None,
        "speaking_style": "formal, brief",
    }
    npc_profile.update({k: v for k, v in _try_load_npc_profile(npc_id).items() if v})

    # Pre-Hint
    pre_ctx = {
        "user_text": user_text,
        "npc_id": npc_id,
        "slot_name": slot_name,
        "last_emotion": None,
        "npc_profile": npc_profile,
        "emotion_schema": emo_schema_rt,
    }
    pre = pre_hint(pre_ctx)

    # 模拟草稿（不调API）；若未给则根据 pre 的 style 给个中性句
    if not simulated_draft:
        prefix = ""
        px = pre.get("style_hooks", {}).get("prefix") or []
        if px and isinstance(px, list) and px[0]:
            prefix = px[0] + " "
        simulated_draft = f"{prefix}I will check and let you know shortly."

    # Post-Infer
    post_ctx = {
        "npc_profile": {"emotion_range": npc_profile.get("emotion_range")},
        "emotion_schema": emo_schema_rt,
    }
    post = post_infer(simulated_draft, post_ctx)

    # 观察项（不改变你的 controller 逻辑）
    post_conf = float(post.get("confidence") or 0.0)
    target_emotion = post.get("emotion_from_content") or pre.get("emotion_hint")
    pre_emotion = pre.get("emotion_hint")
    suggest_rewrite = (post_conf >= 0.7) and (target_emotion != pre_emotion)

    return {
        "input": {
            "user_text": user_text,
            "npc_id": npc_id,
            "slot_name": slot_name,
            "simulated_draft": simulated_draft,
        },
        "pre_hint": pre,
        "post_infer": post,
        "inspect": {
            "pre_emotion": pre_emotion,
            "target_emotion": target_emotion,
            "post_confidence": post_conf,
            "suggest_rewrite": suggest_rewrite,
        },
    }

# ---------------------------
# 内置测试集（参考 smoke tests 并加量）
# ---------------------------
def builtin_suite(npc_id: str):
    """
    内置测试集：覆盖 cheerful/friendly（开心） 与 serious/cautious（紧张/谨慎）场景，
    同时保留少量中性与冲突样本，便于观察 pre/post 一致性与重写触发。
    """
    return [
        # ====== 开心 / 正向 ======
        dict(
            text="Good evening! How are things at the gate?",
            draft="Good evening—everything looks good, no issues to report.",
        ),  # 预期：friendly/neutral
        dict(
            text="Any fun events in the market tonight?",
            draft="Yes—music, lanterns, and plenty of smiles in the crowd.",
        ),  # 预期：cheerful/friendly
        dict(
            text="Business is thriving, right?",
            draft="Indeed—the market is vibrant and the merchants are happy.",
        ),  # 预期：cheerful/friendly

        # ====== 紧张 / 谨慎 / 严肃 ======
        dict(
            text="Any trouble on tonight's patrol?",
            draft="No major incidents, but remain vigilant—there was a suspicious report earlier.",
        ),  # 预期：serious/cautious（draft 含 vigilant/suspicious）
        dict(
            text="Where can I find the black market?",
            draft="I cannot discuss illegal trade—leave this matter alone.",
        ),  # 预期：serious/cautious（注意：真正拒绝交给 filters；此处只看语气）
        dict(
            text="People seem angry; the lord raised taxes again.",
            draft="I understand the frustration, but keep calm and avoid unrest.",
        ),  # 预期：serious/annoyed/neutral 混合（可观察 post 权重）

        # ====== 中性 / 例行 ======
        dict(
            text="What's new in the market?",
            draft="I will check and let you know shortly.",
        ),  # 预期：neutral
        # ====== 冲突 / 对齐验证（开心文本 + 风险提示）======
        dict(
            text="The music festival is joyful, but I heard pickpockets are active.",
            draft="Enjoy the festival, but keep your purse close and stay vigilant.",
        ),  # 预期：cheerful + cautious（post 可能偏 cautious；用于观察 rewrite 策略）

        # ====== 冲突 / 对齐验证（中性问句 + 强正向回答）======
        dict(
            text="Any updates from the merchants?",
            draft="Great news—their profits soared and everyone's delighted!",
        ),  # 预期：post cheerful（与 pre neutral 不一致，用于触发阶段3重写）

        # ====== 快速风险指令（紧张极简）======
        dict(
            text="Is the road safe after sundown?",
            draft="Avoid traveling after dark—bandits were sighted near the crossroads.",
        ),  # 预期：cautious/serious
    ]


# ---------------------------
# CLI
# ---------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user_text", required=False, help="玩家输入文本。若不提供则运行内置测试集。")
    ap.add_argument("--npc_id", default="guard_01", help="NPC id（用于读取 profile，可选）")
    ap.add_argument("--simulated_draft", default=None, help="模拟草稿。如不指定，将自动给出中性句。")
    args = ap.parse_args()

    results: List[Dict[str, Any]] = []
    if args.user_text:
        results.append(run_phase2_case(args.user_text, args.npc_id, args.simulated_draft))
    else:
        for case in builtin_suite(args.npc_id):
            results.append(run_phase2_case(case["text"], args.npc_id, case["draft"]))

    # 只打印一次：整个结果数组
    print(json.dumps(results, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
