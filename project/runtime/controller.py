# -*- coding: utf-8 -*-
"""
runtime/controller.py — The complete pipeline orchestrator
(MODIFIED: Added 'memory_path' to run_once signature)
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional
from pathlib import Path
import json
import sys
import traceback
import datetime

# -----------------------------
# Robust imports (Unchanged)
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
    
    from provider.generator import Generator
    from provider.oocChecker import OOCChecker
    from provider.memory_store import MemoryStore
    from provider.memory_summarizer import MemorySummarizer

except ImportError as e:
    print(f"Import failed: {e}")
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
    
    from provider.generator import Generator
    from provider.oocChecker import OOCChecker
    from provider.memory_store import MemoryStore
    from provider.memory_summarizer import MemorySummarizer

# --- MODIFIED: load_compiled (Unchanged from last step) ---
def load_compiled(config: Dict[str, Any], project_root: Path):
    """
    Loads the compiled.json cache file using the path from the config.
    """
    try:
        cache_dir_str = config.get('app', {}).get('cache_dir', 'runtime/.cache')
        compiled_path = project_root / cache_dir_str / "compiled.json"
        
        if compiled_path.exists():
            return json.loads(compiled_path.read_text(encoding="utf-8"))
        else:
            print(f"[controller] ERROR: compiled.json missing at: {compiled_path}", file=sys.stderr)
            raise RuntimeError(f"compiled.json not found at {compiled_path}")
            
    except Exception as e:
        print(f"[controller] ERROR: compiled.json parse error: {e}", file=sys.stderr)
        raise

# --- get_npc_profile (Logic Unchanged) ---
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

# ----------------------------
# Single-turn pipeline (MODIFIED)
# ----------------------------
def run_once(
    user_text: str, 
    npc_id: str,
    generator: Generator,
    ooc_checker: OOCChecker,
    compiled_data: Dict[str, Any],
    config: Dict[str, Any], 
    memory_store: MemoryStore,
    memory_summarizer: MemorySummarizer,
    # --- MODIFIED: Added 'memory_path' argument ---
    memory_path: str, 
    # --- END MODIFICATION ---
    player_id: str = "P001",
    last_emotion: Optional[str] = None
) -> Dict[str, Any]:
    """
    Executes the full single-turn dialogue pipeline (including memory).
    """
    
    out: Dict[str, Any] = {
        "user_text": user_text,
        "npc_id": npc_id,
        "player_id": player_id,
        "slot": "default",
        "final_text": "I'm not sure what to say.",
        "final_emotion": "neutral",
        "audit": {
            "router": {}, "filters": {}, "retriever": {},
            "emotion_pre": {}, "generation": {}, "ooc_check": {},
            "memory": {"events_added": 0, "facts_written": 0, "facts": []}
        }
    }

    try:
        # --- (1) Routing (MODIFIED) ---
        q = qrouter.prepare(user_text, compiled_data=compiled_data, config=config)
        out["audit"]["router"] = q
        slot_name = q["slot"]
        out["slot"] = slot_name

        # --- (2) Filtering (MODIFIED) ---
        filt = filters_mod.precheck_guardrails(
            user_text, npc_id, compiled_data=compiled_data, config=config
        )
        out["audit"]["filters"] = filt
        if isinstance(filt, dict) and (not filt.get("allow", True)):
            out["final_text"] = filt.get("reply") or "Sorry, I can’t speak to that."
            out["final_emotion"] = "serious"

        # --- (3) Retrieval (MODIFIED) ---
        compiled_lore_public = compiled_data.get("lore_public") or []
        slot_hints = {"must": q["must"], "forbid": q["forbid"], "tags": q.get("tags", [])}
        route_conf = q.get("route_confidence", 0.0)
        
        route_threshold = config.get('thresholds', {}).get('router_fallback_confidence', 0.35)
        require_slot_must = (slot_name not in ["small_talk", "past_story"]) and (route_conf >= route_threshold)
        
        # --- MODIFIED: Pass 'config' and 'memory_path' ---
        r = retriever.retrieve_public_evidence(
            user_text=q["text_norm"],
            config=config,
            memory_path=memory_path, # <-- Now this variable exists
            npc_id=npc_id, 
            slot_hints=slot_hints,
            slot_name=slot_name, 
            require_slot_must=require_slot_must,
            compiled_lore_public=compiled_lore_public,
        )
        # --- END MODIFICATION ---
        
        out["audit"]["retriever"] = r
        evidence = r.get("evidence", []) if isinstance(r, dict) else []
   
        # --- (4) Emotion Pre-Hint (MODIFIED) ---
        npc_profile = get_npc_profile(npc_id, compiled_data)
        emotion_schema = compiled_data.get('emotion_schema_runtime', emotion_engine.DEFAULT_SCHEMA)
        slot_tone_bias = emotion_schema.get('slot_prior', {}).get(slot_name, {"neutral": 1.0})
        emo_ctx = {
            "user_text": user_text, "npc_id": npc_id, "slot_name": slot_name,
            "last_emotion": last_emotion, "npc_profile": npc_profile,
            "emotion_schema": emotion_schema, "slot_tone_bias": {slot_name: slot_tone_bias}
        }
        # --- MODIFIED: Pass 'config' ---
        pre = emotion_engine.pre_hint(emo_ctx, config=config)
        # --- END MODIFICATION ---
        
        out["audit"]["emotion_pre"] = pre

        # --- (5) Real Generation (Unchanged from last step) ---
        persona = f"{npc_profile.get('name', npc_id)} - {npc_profile.get('speaking_style', 'default style')}"
        
        short_mem_k = config.get('memory_policy', {}).get('short_window_k', 10)
        short_memories = memory_store.get_short_window(k=short_mem_k)
        
        selected_memories = [m for m in short_memories if m['npc_id'] == npc_id and m['player_id'] == player_id]
        context_lines = [f"{m['speaker']}({m['player_id'] if m['speaker'] == 'player' else m['npc_id']}): {m['text']} (Emotion:{m['emotion']})" for m in selected_memories]
        print("Short-term memory context:", context_lines)
        ctx = f"User asked: '{q['text_norm']}'\nRecent Dialogue History:\n" + "\n".join(context_lines)
        candidates = generator.generate_candidates(ctx, persona, n=2, evidence=evidence)
        
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
        
        # --- (6) OOC Check (Unchanged) ---
        draft_json_for_ooc = {"text": draft_text, "emotion": draft_emotion, "meta": draft_meta}
        ooc_result = ooc_checker.judge_ooc(ctx, draft_json_for_ooc)
        out["audit"]["ooc_check"] = ooc_result
        
        out["final_text"] = ooc_result.get("text", draft_text) 
        out["final_emotion"] = ooc_result.get("emotion", draft_emotion)

        # --- (7) Memory Pipeline (Unchanged from last step) ---
        try:
            user_event = {
                "speaker": "player", "text": user_text, "emotion": None,
                "player_id": player_id, "npc_id": npc_id,
                "timestamp": datetime.datetime.now()
            }
            memory_store.append_event(user_event)
            
            npc_name = npc_profile.get("name", npc_id) or "npc"
            npc_event = {
                "speaker": npc_name, "text": out["final_text"], "emotion": out["final_emotion"],
                "player_id": player_id, "npc_id": npc_id,
                "timestamp": datetime.datetime.now()
            }
            memory_store.append_event(npc_event)
            out["audit"]["memory"]["events_added"] = 2

            recent_history = memory_store.get_short_window()
            print("Recent history:", recent_history[len(recent_history)-2:])

            summarize_batch = config.get('memory_policy', {}).get('summarize_batch_size', 1)
            facts_to_write = memory_summarizer.summarize(summarize_batch, [user_event, npc_event], slot=slot_name)
            
            if facts_to_write:
                memory_store.write_longterm(player_id, npc_id, facts_to_write)
                out["audit"]["memory"]["facts_written"] = len(facts_to_write)
                out["audit"]["memory"]["facts"] = facts_to_write
        except Exception as e:
            print(f"❌ [controller.run_once] Memory pipeline failed: {e}")
            traceback.print_exc()

        return out
        
    except Exception as e:
        print(f"❌ [controller.run_once] Pipeline execution failed: {e}")
        traceback.print_exc()
        out["final_text"] = "I'm sorry, I seem to have lost my train of thought."
        out["final_emotion"] = "sad"
        return out