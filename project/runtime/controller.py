# -*- coding: utf-8 -*-
"""
runtime/controller.py — Phase 1&2 integrated smoke controller (no real model)
Pipeline: user_text → qrouter_v2 → filters? → retriever → emotion_engine → MOCK GENERATION → emotion post-align
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional
from pathlib import Path
import json
import sys
import traceback

# -----------------------------
# Robust imports for -m runtime.controller
# -----------------------------
if __package__ in (None, ""):
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
else:
    from . import qrouter as qrouter
    from . import retriever
    from . import emotion_engine
    try:
        from . import filters as filters_mod
        HAS_FILTERS = True
    except Exception:
        filters_mod = None
        HAS_FILTERS = False
    from .config import SETTINGS

# -------------------
# Paths
# -------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR    = PROJECT_ROOT / "runtime" / ".cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
COMPILED_PATH = CACHE_DIR / "compiled.json"

# ---------------------------------
# DEV-only demo data (guarded)
# ---------------------------------
DEMO_LORE_PUBLIC: List[Dict[str, Any]] = [
    {"fact_id": "L001", "entity": "City Wall",    "tags": "city, security", "fact": "Obsidian-reinforced walls with night lamps along the parapet.", "visibility": "public"},
    {"fact_id": "L002", "entity": "North Gate",   "tags": "city, law",      "fact": "Opens at sunrise; closes at curfew bell each night.", "visibility": "public"},
    {"fact_id": "L004", "entity": "East Gate",    "tags": "city, trade",    "fact": "Closest gate to the riverfront market.", "visibility": "public"},
    {"fact_id": "L006", "entity": "Market Square","tags": "city, trade",    "fact": "Vendors peak around midday; quiet after dusk.", "visibility": "public"},
    {"fact_id": "L010", "entity": "Guild Hall",   "tags": "guild, admin",   "fact": "Public notices are posted weekly.", "visibility": "public"},
    {"fact_id": "L036", "entity": "Temple Court", "tags": "city, law",      "fact": "Petitions are heard at dawn.", "visibility": "public"},
]
DEMO_ALLOWED_ENTITIES = [
    "City Wall","North Gate","East Gate","Market Square","Guild Hall","Temple Court",
    "Merchant Guild","Adventurers' Guild"
]

def load_compiled() -> Dict[str, Any]:
    """
    生产/严格：必须已有 runtime/.cache/compiled.json；缺失直接报错。
    开发+ALLOW_DEMO：允许使用内置 DEMO_*（仅内存，不落盘）。
    """
    if COMPILED_PATH.exists():
        try:
            return json.loads(COMPILED_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            print("[controller] ERROR: compiled.json parse error:", e, file=sys.stderr)
            if SETTINGS.PRODUCTION or SETTINGS.STRICT_COMPILED:
                raise

    if SETTINGS.ALLOW_DEMO:
        print("[controller] WARN: compiled.json missing — using DEMO data (DEV only).", file=sys.stderr)
        return {
            "allowed_entities": DEMO_ALLOWED_ENTITIES,
            "lore_public": DEMO_LORE_PUBLIC,
        }

    raise RuntimeError(
        "compiled.json not found. Run team-A compiler (compile_data.py) to produce runtime/.cache/compiled.json"
    )

# ----------------------------
# Optional: filters invocation
# ----------------------------
# def run_filters_guard(user_text: str, npc_id: Optional[str], compiled: Dict[str, Any]) -> Optional[Dict[str, Any]]:
#     if not HAS_FILTERS:
#         return None
#     try:
#         fn = getattr(filters_mod, "precheck_guardrails", None)
#         if callable(fn):
#             return fn(user_text=user_text, npc_id=npc_id, compiled=compiled)
#         fn2 = getattr(filters_mod, "apply", None)
#         if callable(fn2):
#             return fn2(user_text=user_text, npc_id=npc_id, compiled=compiled)
#     except Exception as e:
#         print("[controller] filters invocation failed:", e, file=sys.stderr)
#         traceback.print_exc()
#     return None

def run_filters_guard(user_text: str, npc_id: Optional[str], compiled: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not HAS_FILTERS:
        return None
    try:
        fn = getattr(filters_mod, "precheck_guardrails", None)
        if callable(fn):
            # 移除compiled参数，因为precheck_guardrails不需要它
            return fn(user_text=user_text, npc_id=npc_id)
        fn2 = getattr(filters_mod, "apply", None)
        if callable(fn2):
            return fn2(user_text=user_text, npc_id=npc_id)
    except Exception as e:
        print("[controller] filters invocation failed:", e, file=sys.stderr)
        traceback.print_exc()
    return None

# ----------------------------
# Mock model (no fabrication)
# ----------------------------
class MODEL_PLACEHOLDER:
    @staticmethod
    def generate(ctx: Dict[str, Any], evidence: List[Dict[str, Any]]) -> str:
        if not evidence:
            slot = ctx.get("slot_name") or "small_talk"
            if slot == "small_talk":
                return "Just another day—what can I help you with?"
            elif slot == "market_query":
                return "Market’s been ordinary. Nothing specific I can share."
            elif slot == "patrol_info":
                return "Patrol details are handled by the watch; I can only speak in general."
            else:
                return "I can keep it general if you need, but I’ve got no specifics."
        bits = []
        for r in evidence[:2]:
            f = str(r.get("fact","")).strip()
            e = str(r.get("entity","")).strip()
            if f and e: bits.append(f"{e}: {f}")
            elif f:    bits.append(f)
        if not bits:
            return "Nothing public I can share, sorry."
        return " ".join(bits)

# ----------------------------
# Auto slot bias (no preset required)
# ----------------------------
def _auto_slot_bias(slot_name: str, router: Dict[str, Any]) -> Dict[str, float]:
    text = (router.get("text_norm") or "").lower()
    must = set(router.get("must") or [])
    forbid = set(router.get("forbid") or [])
    conf = float(router.get("route_confidence") or 0.0)

    has_greet = any(w in text for w in ["hello", "hi", "hey", "thanks", "thank you"])
    has_market = any(w in text for w in ["market", "buy", "sell", "price", "deal"])
    sensitive_tokens = {"patrol schedule","secret_price","black_market","smuggling","schedule","secret"}
    has_sensitive = any(tok in (must | forbid) for tok in sensitive_tokens)

    if (not must) and has_greet:
        return {"friendly": 0.7, "cheerful": 0.3}
    if has_sensitive:
        return {"serious": 0.8, "neutral": 0.2}
    if has_market:
        return {"friendly": 0.6, "neutral": 0.4}
    if conf < 0.35:
        return {"neutral": 0.6, "friendly": 0.4}
    return {"serious": 0.7, "neutral": 0.3}

# 可选：手工 bias；留空也没事（会自动推断）
SLOT_TONE_BIAS: Dict[str, Dict[str, float]] = {
    # "small_talk":   {"friendly": 0.85, "cheerful": 0.15},
    # "market_query": {"friendly": 0.70, "neutral": 0.30},
    # "patrol_info":  {"serious":  0.80, "neutral":  0.20},
}

# ----------------------------
# Single-turn pipeline
# ----------------------------
def run_once(user_text: str, npc_id: Optional[str]="S001") -> Dict[str, Any]:
    out: Dict[str, Any] = {"slot": None, "router": {}, "filters": None, "retriever": {}, "emotion": {}, "draft": ""}

    compiled = load_compiled()
    compiled_lore_public = compiled.get("lore_public") or []

    # (1) route
    q = qrouter.prepare(user_text)
    out["router"] = q
    slot_name = q["slot"]
    out["slot"] = slot_name

    # (2) filters
    filt = run_filters_guard(user_text, npc_id, compiled)
    out["filters"] = filt
    if isinstance(filt, dict) and (not filt.get("allow", True)):
        out["draft"] = filt.get("reply") or "Sorry, I can’t speak to that."
        slot_bias = SLOT_TONE_BIAS.get(slot_name) or _auto_slot_bias(slot_name, q)
        emo_ctx = {
            "user_text": user_text,
            "npc_id": npc_id,
            "slot_name": slot_name,
            "last_emotion": None,
            "npc_profile": {
                "baseline_emotion": "serious",
                "emotion_range": emotion_engine.DEFAULT_SCHEMA["labels"],
                "style_emotion_map": {
                    "cheerful": {"prefix": ["Hey,"], "suffix": ["!"], "tone": "bright"},
                    "friendly": {"prefix": ["Sure,"], "suffix": [],    "tone": "warm"},
                    "serious":  {"prefix": ["Listen,"], "suffix": ["."], "tone": "flat"},
                    "neutral":  {"tone": "neutral"},
                },
            },
            "emotion_schema": emotion_engine.DEFAULT_SCHEMA,
            "slot_tone_bias": {slot_name: slot_bias},
        }
        pre = emotion_engine.pre_hint(emo_ctx)
        out["emotion"] = {"pre": pre, "post": None, "final": pre["emotion_hint"], "style": pre["style_hooks"]}
        return out

    # (3) retrieve（small_talk 跳过检索）
    slot_hints = {"must": q["must"], "forbid": q["forbid"], "tags": q.get("tags", [])}
    route_conf = q.get("route_confidence", 0.0)
    relaxed = (slot_name == "small_talk") or (route_conf < 0.35)

    if slot_name == "small_talk":
        r = {"flags": {"insufficient": True}, "evidence": [], "audit": {"must": [], "forbid": []}}
    else:
        if not compiled_lore_public and (SETTINGS.PRODUCTION or SETTINGS.STRICT_COMPILED):
            raise RuntimeError("[controller] lore_public missing. Ensure compiled.json provides 'lore_public'.")
        r = retriever.retrieve_public_evidence(
            user_text=q["text_norm"],
            npc_id=npc_id,
            slot_hints=slot_hints,
            slot_name=slot_name,
            require_slot_must=(not relaxed),
            compiled_lore_public=compiled_lore_public,
        )
    out["retriever"] = r
    evidence = r.get("evidence", []) if isinstance(r, dict) else []

    # (4) emotion pre
    slot_bias = SLOT_TONE_BIAS.get(slot_name) or _auto_slot_bias(slot_name, q)
    emo_ctx = {
        "user_text": user_text,
        "npc_id": npc_id,
        "slot_name": slot_name,
        "last_emotion": None,
        "npc_profile": {
            "baseline_emotion": "serious",
            "emotion_range": emotion_engine.DEFAULT_SCHEMA["labels"],
            "speaking_style": "formal, brief",
            "style_emotion_map": {
                "cheerful": {"prefix": ["Hey,"], "suffix": ["!"], "tone": "bright"},
                "friendly": {"prefix": ["Sure,"], "suffix": [],    "tone": "warm"},
                "serious":  {"prefix": ["Listen,"], "suffix": ["."], "tone": "flat"},
                "neutral":  {"tone": "neutral"},
            },
        },
        "emotion_schema": emotion_engine.DEFAULT_SCHEMA,
        "slot_tone_bias": {slot_name: slot_bias},
    }
    pre = emotion_engine.pre_hint(emo_ctx)

    if slot_name == "small_talk" and pre.get("emotion_hint") == "neutral":
        pre["emotion_hint"] = "friendly"
        pre["style_hooks"] = emotion_engine.realize_style("friendly", emo_ctx["npc_profile"]["style_emotion_map"])

    # (5) mock generate
    if slot_name == "small_talk":
        style = pre["style_hooks"]
        prefix = " ".join(style.get("prefix") or [])
        suffix = " ".join(style.get("suffix") or [])
        core = "Just another day—what can I help you with?"
        draft = f"{(prefix + ' ') if prefix else ''}{core}{(' ' + suffix) if suffix else ''}".strip()
    else:
        draft = MODEL_PLACEHOLDER.generate({"slot_name": slot_name}, evidence)
    out["draft"] = draft

    # (6) emotion post + zero-signal neutral fallback
    draft_emotion = pre["emotion_hint"]
    post = emotion_engine.post_infer(draft, draft_emotion, emo_ctx)
    post_conf = float(post.get("confidence", 0.0) or 0.0)
    post_dbg = (post.get("debug") or {})
    raw = (post_dbg.get("raw_scores") or {})
    degenerate_neutral = (
        (post.get("matches") in ([], None)) and
        (raw.get("neutral", 0.0) == 1.0) and
        (abs(sum(raw.values()) - 1.0) < 1e-9)
    )
    if degenerate_neutral or (post_conf < 0.55):
        final_em = pre["emotion_hint"]
    else:
        final_em = post.get("emotion_from_content") or pre["emotion_hint"]

    style = emotion_engine.realize_style(final_em, emo_ctx["npc_profile"]["style_emotion_map"])
    out["emotion"] = {"pre": pre, "post": post, "final": final_em, "style": style}

    return out
