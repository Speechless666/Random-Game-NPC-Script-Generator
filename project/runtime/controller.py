# -*- coding: utf-8 -*-
"""
runtime/controller.py — 完整的管线编排器
(已更新：包含记忆管线)
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional
from pathlib import Path
import json
import sys
import traceback

# -----------------------------
# Robust imports (已修复)
# -----------------------------
try:
    from runtime import qrouter as qrouter
    from runtime import retriever
    from runtime import emotion_engine
    try:
        from runtime import filters as filters_mod
        HAS_FILTERS = True
    except Exception:
        filters_mod = None
        HAS_FILTERS = False
    from runtime.config import SETTINGS
    
    from provider.generator import Generator
    from provider.oocChecker import OOCChecker
    # --- 新增：导入记忆模块 ---
    from provider.memory_store import MemoryStore
    from provider.memory_summarizer import MemorySummarizer
    # --- 结束新增 ---

except ImportError as e:
    print(f"导入失败: {e}")
    THIS = Path(__file__).resolve()
    PROJECT_ROOT = THIS.parents[1]
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    
    from runtime import qrouter as qrouter
    from runtime import retriever
    from runtime import emotion_engine
    try:
        from runtime import filters as filters_mod
        HAS_FILTERS = True
    except Exception:
        filters_mod = None
        HAS_FILTERS = False
    from runtime.config import SETTINGS
    from provider.generator import Generator
    from provider.oocChecker import OOCChecker
    # --- 新增：导入记忆模块 ---
    from provider.memory_store import MemoryStore
    from provider.memory_summarizer import MemorySummarizer
    # --- 结束新增 ---


# ... (Paths, Demo data, load_compiled, run_filters_guard, get_npc_profile 保持不变) ...
# (我们假设它们在这里)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR    = PROJECT_ROOT / "runtime" / ".cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
COMPILED_PATH = CACHE_DIR / "compiled.json"
def load_compiled():
    # ( ... 完整函数 ... )
    if COMPILED_PATH.exists():
        try:
            return json.loads(COMPILED_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            print("[controller] ERROR: compiled.json parse error:", e, file=sys.stderr)
            if SETTINGS.PRODUCTION or SETTINGS.STRICT_COMPILED: raise
    if SETTINGS.ALLOW_DEMO:
        print("[controller] WARN: compiled.json missing — using DEMO data (DEV only).", file=sys.stderr)
        return {
            "allowed_entities": [], "lore_public": [], "npc": [],
            "emotion_schema_runtime": emotion_engine.DEFAULT_SCHEMA,
        }
    raise RuntimeError("compiled.json not found.")

def run_filters_guard(user_text: str, npc_id: Optional[str], compiled: Dict[str, Any]):
    if not HAS_FILTERS: return None
    try:
        fn = getattr(filters_mod, "precheck_guardrails", None)
        if callable(fn): return fn(user_text=user_text, npc_id=npc_id)
        fn2 = getattr(filters_mod, "apply", None)
        if callable(fn2): return fn2(user_text=user_text, npc_id=npc_id)
    except Exception as e: print("[controller] filters invocation failed:", e, file=sys.stderr)
    return None

def get_npc_profile(npc_id: str, compiled_data: Dict[str, Any]):
    npcs = compiled_data.get('npc', [])
    for npc in npcs:
        if npc.get('npc_id') == npc_id: return npc
    print(f"[WARN] NPC ID {npc_id} not found. Using default profile.")
    return {
        "npc_id": npc_id, "name": npc_id, "role": "villager",
        "baseline_emotion": "neutral", "emotion_range": ["neutral"],
        "speaking_style": "formal", "style_emotion_map": {}
    }
# ... (以上是保持不变的辅助函数) ...


# ----------------------------
# Single-turn pipeline (已修改)
# ----------------------------
def run_once(
    user_text: str, 
    npc_id: str,
    generator: Generator,
    ooc_checker: OOCChecker,
    compiled_data: Dict[str, Any],
    # --- 新增参数 ---
    memory_store: MemoryStore,
    memory_summarizer: MemorySummarizer,
    player_id: str = "P001", # 假设一个默认 Player ID
    # --- 结束新增 ---
    last_emotion: Optional[str] = None
) -> Dict[str, Any]:
    """
    执行完整的单轮对话管线 (包含记忆)。
    """
    
    out: Dict[str, Any] = {
        "user_text": user_text,
        "npc_id": npc_id,
        "player_id": player_id, # <-- 新增
        "slot": "default",
        "final_text": "I'm not sure what to say.",
        "final_emotion": "neutral",
        "audit": {
            "router": {}, "filters": {}, "retriever": {},
            "emotion_pre": {}, "generation": {}, "ooc_check": {},
            # --- 新增审计 ---
            "memory": {"events_added": 0, "facts_written": 0, "facts": []}
            # --- 结束新增 ---
        }
    }

    try:
        # --- (1) 路由 (Phase 1) ---
        q = qrouter.prepare(user_text)
        out["audit"]["router"] = q
        slot_name = q["slot"]
        out["slot"] = slot_name

        # --- (2) 过滤 (Phase 2) ---
        filt = run_filters_guard(user_text, npc_id, compiled_data)
        out["audit"]["filters"] = filt
        if isinstance(filt, dict) and (not filt.get("allow", True)):
            out["final_text"] = filt.get("reply") or "Sorry, I can’t speak to that."
            out["final_emotion"] = "serious"
            # (注意：即使被过滤，我们仍然应该记录这个交互)
            # return out # <-- 不再提前返回

        # --- (3) 检索 (Phase 2) ---
        # ( ... 检索逻辑 ... )
        compiled_lore_public = compiled_data.get("lore_public") or []
        slot_hints = {"must": q["must"], "forbid": q["forbid"], "tags": q.get("tags", [])}
        route_conf = q.get("route_confidence", 0.0)
        require_slot_must = (slot_name not in ["small_talk", "past_story"]) and (route_conf >= 0.35)
        r = retriever.retrieve_public_evidence(
            user_text=q["text_norm"], npc_id=npc_id, slot_hints=slot_hints,
            slot_name=slot_name, require_slot_must=require_slot_must,
            compiled_lore_public=compiled_lore_public,
        )
        out["audit"]["retriever"] = r
        evidence = r.get("evidence", []) if isinstance(r, dict) else []

        # --- (4) 情绪 Pre-Hint (Phase 2) ---
        # ( ... 情绪逻辑 ... )
        npc_profile = get_npc_profile(npc_id, compiled_data)
        emotion_schema = compiled_data.get('emotion_schema_runtime', emotion_engine.DEFAULT_SCHEMA)
        slot_tone_bias = emotion_schema.get('slot_prior', {}).get(slot_name, {"neutral": 1.0})
        emo_ctx = {
            "user_text": user_text, "npc_id": npc_id, "slot_name": slot_name,
            "last_emotion": last_emotion, "npc_profile": npc_profile,
            "emotion_schema": emotion_schema, "slot_tone_bias": {slot_name: slot_tone_bias}
        }
        pre = emotion_engine.pre_hint(emo_ctx)
        out["audit"]["emotion_pre"] = pre

        # --- (5) 真实生成 (Phase 3) ---
        # ( ... 生成逻辑 ... )
        persona = f"{npc_profile.get('name', npc_id)} - {npc_profile.get('speaking_style', 'default style')}"
        ctx = f"User asked: '{q['text_norm']}'" 
        candidates = generator.generate_candidates(ctx, persona, n=2, evidence=evidence)
        
        # 如果被过滤器拦下，这里就不生成
        if isinstance(filt, dict) and (not filt.get("allow", True)):
             draft_text = filt.get("reply") or "Sorry, I can’t speak to that."
             draft_emotion = "serious"
             draft_meta = {}
        elif not candidates:
            draft_text = "I'm not sure what to say to that."
            draft_emotion = "neutral"
            draft_meta = {}
        else:
            best_candidate = generator.rank(candidates, persona, ctx)
            out["audit"]["generation"] = {"all_candidates": candidates, "best_candidate": best_candidate}
            draft_text = best_candidate.get('draft', {}).get('text', '')
            draft_emotion = best_candidate.get('draft', {}).get('meta', {}).get('sentiment', 'neutral')
            draft_meta = best_candidate.get('draft', {}).get('meta', {})
        
        # --- (6) OOC 检查 (Phase 3) ---
        # ( ... OOC 逻辑 ... )
        draft_json_for_ooc = {"text": draft_text, "emotion": draft_emotion, "meta": draft_meta}
        ooc_result = ooc_checker.judge_ooc(ctx, draft_json_for_ooc)
        out["audit"]["ooc_check"] = ooc_result
        
        out["final_text"] = ooc_result.get("text", draft_text) 
        out["final_emotion"] = ooc_result.get("emotion", draft_emotion)

        # --- (7) 记忆管线 (Phase 3) ---
        try:
            # 1. 记录用户事件
            user_event = {
                "speaker": "player", 
                "text": user_text, 
                "emotion": None, # (我们通常不分析玩家情绪)
                "player_id": player_id, 
                "npc_id": npc_id
            }
            memory_store.append_event(user_event)
            
            # 2. 记录 NPC 事件
            npc_event = {
                "speaker": "npc", 
                "text": out["final_text"], 
                "emotion": out["final_emotion"],
                "player_id": player_id,
                "npc_id": npc_id
            }
            memory_store.append_event(npc_event)
            out["audit"]["memory"]["events_added"] = 2

            # 3. 尝试总结
            # (注意: 在真实应用中，这可能不会每轮都跑，而是异步或N轮一次)
            recent_history = memory_store.get_short_window()
            
            facts_to_write = memory_summarizer.summarize(recent_history, slot=slot_name)
            
            if facts_to_write:
                # 4. 写入长期记忆
                memory_store.write_longterm(player_id, npc_id, facts_to_write)
                out["audit"]["memory"]["facts_written"] = len(facts_to_write)
                out["audit"]["memory"]["facts"] = facts_to_write
        except Exception as e:
            print(f"❌ [controller.run_once] 记忆管线失败: {e}")
            traceback.print_exc()

        return out
        
    except Exception as e:
        print(f"❌ [controller.run_once] 管线执行失败: {e}")
        traceback.print_exc()
        out["final_text"] = "I'm sorry, I seem to have lost my train of thought."
        out["final_emotion"] = "sad"
        return out