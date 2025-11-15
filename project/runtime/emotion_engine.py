# -*- coding: utf-8 -*-
"""
emotion_engine.py — Phase 2 · Emotion & Style (Two-step: Pre-Hint → Post-Align)
(MODIFIED: Reads all weights and thresholds from config)
"""

from __future__ import annotations
from typing import Dict, Any, List, Tuple, Optional
import re

# ==================
# Tunable weights (REMOVED)
# ==================
# --- REMOVED: All hardcoded W_... and HYST_TAU variables ---
# (These will be loaded from config inside the functions)

_WORD = re.compile(r"[a-zA-Z']+")

# ==========================
# Emotion aliases & fallback (Logic Unchanged)
# ==========================
EMOTION_ALIASES = {
    "calm": "neutral", "plain": "neutral", "formal": "serious",
    "stern": "serious", "warm": "friendly", "happy": "cheerful",
    "upbeat": "cheerful", "irritated": "annoyed", "blue": "sad",
}
EMOTION_FALLBACK_CHAIN = {
    "friendly": ["cheerful", "neutral"],
    "cheerful": ["friendly", "neutral"],
    "serious":  ["neutral", "friendly"],
    "annoyed":  ["serious", "neutral"],
    "sad":      ["serious", "neutral"],
}

# ==========================
# DEFAULT_SCHEMA (Logic Unchanged)
# ==========================
DEFAULT_SCHEMA: Dict[str, Any] = {
    "labels": ["neutral", "friendly", "cheerful", "serious", "annoyed", "sad"],
    "tone_map": {
        "serious":  {"serious": 0.6, "neutral": 0.4},
        "friendly": {"friendly": 0.6, "cheerful": 0.4},
        "formal":   {"serious": 0.5, "neutral": 0.5},
        "casual":   {"friendly": 0.5, "cheerful": 0.5}
    },
    "triggers": {},
    "content":  {},
}

# =============
# Util helpers (Logic Unchanged)
# =============
def _norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()

def _labels(ctx: Dict[str, Any]) -> List[str]:
    # (Logic Unchanged)
    labels = list(ctx.get("emotion_schema", {}).get("emotions")
                  or ctx.get("emotion_schema", {}).get("labels")
                  or DEFAULT_SCHEMA["labels"])
    seen, out = set(), []
    for l in labels:
        if l not in seen:
            out.append(l); seen.add(l)
    return out

def _tone_map(ctx: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
    # (Logic Unchanged)
    return dict(ctx.get("emotion_schema", {}).get("tone_map") or DEFAULT_SCHEMA["tone_map"])

def _triggers(ctx: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    # (Logic Unchanged)
    return dict(ctx.get("emotion_schema", {}).get("triggers") or DEFAULT_SCHEMA["triggers"])

def _content(ctx: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    # (Logic Unchanged)
    return dict(ctx.get("emotion_schema", {}).get("content") or DEFAULT_SCHEMA["content"])

def _blank_scores(labels: List[str]) -> Dict[str, float]:
    # (Logic Unchanged)
    return {e: 0.0 for e in labels}

def _clamp_to_range(emotion: str, allowed: Any, original_scores: Dict[str, float] = None) -> str:
    """Clamps the emotion to the NPC's allowed range - based on original score weight"""
    # (Logic Unchanged)
    if not allowed:
        return emotion
    em = EMOTION_ALIASES.get(emotion, emotion).lower()
    if isinstance(allowed, str):
        allowed_emotions = [e.strip().lower() for e in allowed.split(',')]
    elif isinstance(allowed, list):
        allowed_emotions = [e.lower() if isinstance(e, str) else str(e) for e in allowed]
    else:
        return em
    
    if em in allowed_emotions:
        return em
    else:
        if original_scores:
            allowed_with_scores = [(e, original_scores.get(e, 0)) for e in allowed_emotions if e in original_scores]
            if allowed_with_scores:
                return max(allowed_with_scores, key=lambda x: x[1])[0]
        return allowed_emotions[0] if allowed_emotions else "neutral"

def _mix_into(base: Dict[str, float], add: Dict[str, float], weight: float) -> None:
    # (Logic Unchanged)
    if weight <= 0.0 or not add:
        return
    for k, v in add.items():
        if k in base:
            base[k] += weight * float(v)

def _normalize_scores(scores: Dict[str, float]) -> Dict[str, float]:
    # (Logic Unchanged)
    if not scores:
        return scores
    total = sum(max(0.0, v) for v in scores.values())
    if total <= 0.0:
        if "neutral" in scores:
            scores["neutral"] = 1.0
        else:
            first = next(iter(scores))
            scores[first] = 1.0
        total = sum(scores.values())
    for k in list(scores.keys()):
        scores[k] = max(0.0, scores[k]) / total
    return scores

# ==========================
# 1) Pre-Hint (MODIFIED)
# ==========================
def pre_hint(ctx: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]: # <-- ADDED config
    labels = _labels(ctx)
    scores = _blank_scores(labels)
    dbg: Dict[str, Any] = {}

    # --- MODIFIED: Load weights from config ---
    weights = config.get('weights', {})
    w_base = weights.get('emotion_w_base', 0.20)
    w_slot = weights.get('emotion_w_slot', 0.15)
    w_trig = weights.get('emotion_w_trig', 0.50)
    w_inert = weights.get('emotion_w_inert', 0.10)
    w_api = weights.get('emotion_w_api', 0.0)
    
    thresholds = config.get('thresholds', {})
    hyst_tau = thresholds.get('emotion_hyst_tau', 0.25)
    strong_trigger_sum = thresholds.get('emotion_strong_trigger_sum', 0.90)
    # --- END MODIFICATION ---

    base_em = _norm(ctx.get("npc_profile", {}).get("baseline_emotion"))
    if base_em and base_em in scores:
        scores[base_em] += w_base # <-- Use config weight
    dbg["baseline"] = base_em or None

    slot_name = ctx.get("slot_name") or ""
    slot_bias_map = {}
    if isinstance(ctx.get("slot_tone_bias"), dict):
        slot_bias_map = dict(ctx["slot_tone_bias"].get(slot_name, {}) or {})
    if not slot_bias_map:
        prof = ctx.get("npc_profile", {}) or {}
        style_kw = _norm(prof.get("speaking_style") or "").split(",")[0].strip() if prof.get("speaking_style") else None
        tone_map = _tone_map(ctx)
        if style_kw in tone_map:
            slot_bias_map = dict(tone_map[style_kw])
    if slot_bias_map:
        _mix_into(scores, slot_bias_map, w_slot) # <-- Use config weight
    dbg["slot_prior"] = slot_bias_map

    trig_votes, trig_hits = _trigger_votes(ctx.get("user_text") or "", ctx)
    _mix_into(scores, trig_votes, w_trig) # <-- Use config weight
    dbg["trigger_hits"] = trig_hits
    dbg["trigger_votes"] = trig_votes

    last = _norm(ctx.get("last_emotion"))
    if last and last in scores:
        scores[last] += w_inert # <-- Use config weight
    dbg["last_emotion"] = last or None

    if w_api > 0.0 and isinstance(ctx.get("api_votes"), dict):
        _mix_into(scores, ctx["api_votes"], w_api) # <-- Use config weight
        dbg["api_votes"] = ctx["api_votes"]

    scores = _normalize_scores(scores)
    best = max(scores.items(), key=lambda kv: kv[1])[0]

    total_trig_mass = sum(float(v) for v in (dbg.get("trigger_votes") or {}).values())
    
    # --- MODIFIED: Use config thresholds ---
    strong_trigger = total_trig_mass >= strong_trigger_sum

    if not strong_trigger and last and last in scores and (scores[best] - scores[last]) < hyst_tau:
    # --- END MODIFICATION ---
        best = last
        dbg["hysteresis_kept"] = True
    else:
        dbg["hysteresis_kept"] = False
    dbg["strong_trigger_bypass"] = strong_trigger
    dbg["scores"] = scores

    allowed = ctx.get("npc_profile", {}).get("emotion_range")
    best = _clamp_to_range(best, allowed, scores)

    style = realize_style(best, ctx.get("npc_profile", {}).get("style_emotion_map"))

    return {"emotion_hint": best, "style_hooks": style, "debug": dbg}

# ===============================
# 2) Post-Infer (MODIFIED)
# ===============================
def post_infer(output_text: str, draft_emotion: str, ctx: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]: # <-- ADDED config
    """
    Uses the model's provided emotion, but calculates confidence based on config heuristics.
    """
    labels = _labels(ctx)
    
    emotion_from_content = draft_emotion
    
    # --- MODIFIED: Pass config to confidence calculator ---
    confidence = _calculate_confidence_based_on_content(output_text, config=config)
    # --- END MODIFICATION ---
    
    return {
        "emotion_from_content": emotion_from_content,
        "confidence": confidence,
        "matches": [],
        "debug": {
            "source": "draft_emotion",
            "raw_scores": {emotion_from_content: 1.0},
            "confidence_factors": f"base_conf + heuristics (see config['thresholds'])"
        }
    }

# --- MODIFIED: Function signature ---
def _calculate_confidence_based_on_content(text: str, config: Dict[str, Any]) -> float:
# --- END MODIFICATION ---
    """
    Simple heuristic for emotion confidence based on text content, using config values.
    """
    if not text:
        return 0.0
    
    # --- MODIFIED: Load heuristics from config ---
    thresh = config.get('thresholds', {})
    conf_base = thresh.get('emotion_conf_base', 0.7)
    conf_long_thresh = thresh.get('emotion_conf_long_thresh', 10)
    conf_long_bonus = thresh.get('emotion_conf_long_bonus', 0.1)
    conf_short_thresh = thresh.get('emotion_conf_short_thresh', 3)
    conf_short_penalty = thresh.get('emotion_conf_short_penalty', 0.2)
    conf_exclaim_bonus = thresh.get('emotion_conf_exclaim_bonus', 0.1)
    conf_question_bonus = thresh.get('emotion_conf_question_bonus', 0.1)
    conf_min = thresh.get('emotion_conf_min', 0.3)
    conf_max = thresh.get('emotion_conf_max', 0.95)
    # --- END MODIFICATION ---

    confidence = conf_base # <-- Use config value
    
    word_count = len(text.split())
    if word_count >= conf_long_thresh: # <-- Use config value
        confidence += conf_long_bonus # <-- Use config value
    elif word_count <= conf_short_thresh: # <-- Use config value
        confidence -= conf_short_penalty # <-- Use config value
    
    if "!" in text:
        confidence += conf_exclaim_bonus # <-- Use config value
    if "?" in text and text.count("?") > 1:
        confidence += conf_question_bonus # <-- Use config value
    
    return max(conf_min, min(conf_max, confidence)) # <-- Use config values

# ==============================
# 3) Style realization (Logic Unchanged)
# ==============================
def realize_style(emotion: str, style_map: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    # (Logic Unchanged)
    em = EMOTION_ALIASES.get(emotion, emotion) if emotion else "neutral"
    style: Dict[str, Any] = {"prefix": [], "suffix": [], "tone": (em or "neutral")}

    if not isinstance(style_map, dict):
        if em == "cheerful":
            return {"prefix": ["Hey,"], "suffix": ["!"], "tone": "bright"}
        if em == "friendly":
            return {"prefix": ["Sure,"], "suffix": [], "tone": "warm"}
        if em == "serious":
            return {"prefix": ["Listen,"], "suffix": ["."], "tone": "flat"}
        return style

    m = style_map.get(em)
    if not m:
        for alt in EMOTION_FALLBACK_CHAIN.get(em, []):
            m = style_map.get(alt)
            if m: break
        if not m:
            m = style_map.get("neutral", None)

    if isinstance(m, dict):
        for k in ("prefix", "suffix", "tone"):
            if k in m: style[k] = m[k]
    return style

# ==========================================
# Internal: trigger votes (Logic Unchanged)
# ==========================================
def _trigger_votes(text: str, ctx: Dict[str, Any]) -> Tuple[Dict[str, float], List[str]]:
    # (Logic Unchanged)
    t = _norm(text)
    labels = _labels(ctx)
    scores = _blank_scores(labels)
    hits: List[str] = []
    trig = _triggers(ctx)
    for _, cfg in trig.items():
        phrases = cfg.get("phrases") or cfg.get("keywords") or []
        for p in phrases:
            p = str(p).lower().strip()
            if p and p in t:
                hits.append(p)
                for e, w in (cfg.get("votes") or {}).items():
                    if e in scores:
                        scores[e] += float(w)
    return scores, hits