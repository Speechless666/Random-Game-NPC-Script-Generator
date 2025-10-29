# -*- coding: utf-8 -*-
"""
emotion_engine.py — Phase 2 · Emotion & Style (Two-step: Pre-Hint → Post-Align)

This module **does not generate natural language**. It only:
  1) pre_hint(ctx)        → provide a *weak* emotion hint + style hooks **before** generation
  2) post_infer(text,ctx) → infer emotion **from drafted content** to align tone with what was said
  3) realize_style(emotion, style_map) → map emotion → style hooks (prefix / suffix / tone)

Schema-driven (team A compiles emotion_schema.yaml upstream).
"""

from __future__ import annotations
from typing import Dict, Any, List, Tuple, Optional
import re

# ==================
# Tunable parameters (adjusted to be more responsive)
# ==================
W_BASE   = 0.20  # baseline prior from npc_profile.baseline_emotion  (↓ from 0.25)
W_SLOT   = 0.15  # slot tone bias prior (schema.tone_map / ctx.slot_tone_bias) (↓ from 0.20)
W_TRIG   = 0.50  # lexical trigger votes from user_text (pre phase)  (↑ from 0.40)
W_INERT  = 0.10  # inertia from last_emotion (same)
W_API    = 0.00  # reserved
HYST_TAU = 0.25  # hysteresis keep threshold (↓ from 0.40 → easier to switch)

# Strong-trigger bypass (new):
# If the sum of trigger votes mass >= this threshold, bypass hysteresis.
STRONG_TRIGGER_SUM = 0.90

_WORD = re.compile(r"[a-zA-Z']+")

# ==========================
# Emotion aliases & fallback
# ==========================
EMOTION_ALIASES = {
    "calm": "neutral", "plain": "neutral", "formal": "serious",
    "stern": "serious", "warm": "friendly", "happy": "cheerful",
    "upbeat": "cheerful", "irritated": "annoyed", "blue": "sad",
}

# If target style missing, fall back by similarity chain
EMOTION_FALLBACK_CHAIN = {
    "friendly": ["cheerful", "neutral"],
    "cheerful": ["friendly", "neutral"],
    "serious":  ["neutral", "friendly"],
    "annoyed":  ["serious", "neutral"],
    "sad":      ["serious", "neutral"],
}

# ==========================
# Default schema (safe stub)
# ==========================
DEFAULT_SCHEMA: Dict[str, Any] = {
    "labels": ["neutral", "friendly", "cheerful", "serious", "annoyed", "sad"],
    "transforms": {
        "neutral":  ["calm", "plain"],
        "friendly": ["warm"],
        "cheerful": ["happy", "upbeat"],
        "serious":  ["formal", "stern"],
        "annoyed":  ["irritated", "grumpy"],
        "sad":      ["down", "blue"],
    },
    "triggers": {
        "gratitude": {
            "phrases": ["thanks", "thank you", "appreciate it"],
            "votes": {"friendly": 0.7, "cheerful": 0.4}
        },
        "apology": {
            "phrases": ["sorry", "apologies"],
            "votes": {"serious": 0.5, "sad": 0.5}
        },
        "threat": {
            "phrases": ["watch it", "careful", "don’t try me", "back off"],
            "votes": {"annoyed": 1.0, "serious": 0.5}
        },
        "greet": {
            "phrases": ["hello", "hi there", "hey"],
            "votes": {"friendly": 0.6}
        },
    },
    "content": {
        "off_duty": {
            "phrases": ["free today", "taking it easy", "off-duty", "leisure"],
            "votes": {"cheerful": 1.0, "friendly": 0.7}
        },
        "tired": {
            "phrases": ["tired", "exhausted", "lack of sleep", "sick"],
            "votes": {"sad": 1.0, "serious": 0.6}
        },
        "lucky": {
            "phrases": ["good day", "lucky", "finished early", "went well"],
            "votes": {"cheerful": 1.0, "friendly": 0.6}
        },
    },
    "tone_map": {
        "serious":  {"serious": 0.6, "neutral": 0.4},
        "friendly": {"friendly": 0.6, "cheerful": 0.4},
        "formal":   {"serious": 0.5, "neutral": 0.5},
        "casual":   {"friendly": 0.5, "cheerful": 0.5}
    }
}

# =============
# Util helpers
# =============

def _norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()

def _labels(ctx: Dict[str, Any]) -> List[str]:
    labels = list(ctx.get("emotion_schema", {}).get("emotions")
                  or ctx.get("emotion_schema", {}).get("labels")
                  or DEFAULT_SCHEMA["labels"])
    seen, out = set(), []
    for l in labels:
        if l not in seen:
            out.append(l); seen.add(l)
    return out

def _tone_map(ctx: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
    return dict(ctx.get("emotion_schema", {}).get("tone_map") or DEFAULT_SCHEMA["tone_map"])

def _triggers(ctx: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return dict(ctx.get("emotion_schema", {}).get("triggers") or DEFAULT_SCHEMA["triggers"])

def _content(ctx: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return dict(ctx.get("emotion_schema", {}).get("content") or DEFAULT_SCHEMA["content"])

def _blank_scores(labels: List[str]) -> Dict[str, float]:
    return {e: 0.0 for e in labels}

def _clamp_to_range(emotion: str, allowed: Optional[List[str]]) -> str:
    if not allowed:
        return emotion
    # alias before clamp
    em = EMOTION_ALIASES.get(emotion, emotion)
    return em if em in allowed else (allowed[0] if allowed else em)

def _mix_into(base: Dict[str, float], add: Dict[str, float], weight: float) -> None:
    if weight <= 0.0 or not add:
        return
    for k, v in add.items():
        if k in base:
            base[k] += weight * float(v)

def _normalize_scores(scores: Dict[str, float]) -> Dict[str, float]:
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
# 1) Pre-Hint (pre-generation)
# ==========================

def pre_hint(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Provide a *weak* emotion hint before generation (safety baseline only).
    Returns: {"emotion_hint": str, "style_hooks": dict, "debug": {...}}
    """
    labels = _labels(ctx)
    scores = _blank_scores(labels)
    dbg: Dict[str, Any] = {}

    # A) baseline from NPC profile
    base_em = _norm(ctx.get("npc_profile", {}).get("baseline_emotion"))
    if base_em and base_em in scores:
        scores[base_em] += W_BASE
    dbg["baseline"] = base_em or None

    # B) slot tone prior
    slot_name = ctx.get("slot_name") or ""
    slot_bias_map = {}
    if isinstance(ctx.get("slot_tone_bias"), dict):
        slot_bias_map = dict(ctx["slot_tone_bias"].get(slot_name, {}) or {})
    if not slot_bias_map:
        # try infer from profile.speaking_style (very weak heuristic)
        prof = ctx.get("npc_profile", {}) or {}
        style_kw = _norm(prof.get("speaking_style") or "").split(",")[0].strip() if prof.get("speaking_style") else None
        tone_map = _tone_map(ctx)
        if style_kw in tone_map:
            slot_bias_map = dict(tone_map[style_kw])
    if slot_bias_map:
        _mix_into(scores, slot_bias_map, W_SLOT)
    dbg["slot_prior"] = slot_bias_map

    # C) lexical triggers from user_text
    trig_votes, trig_hits = _trigger_votes(ctx.get("user_text") or "", ctx)
    _mix_into(scores, trig_votes, W_TRIG)
    dbg["trigger_hits"] = trig_hits
    dbg["trigger_votes"] = trig_votes

    # D) inertia from last emotion
    last = _norm(ctx.get("last_emotion"))
    if last and last in scores:
        scores[last] += W_INERT
    dbg["last_emotion"] = last or None

    # E) future external API votes (reserved)
    if W_API > 0.0 and isinstance(ctx.get("api_votes"), dict):
        _mix_into(scores, ctx["api_votes"], W_API)
        dbg["api_votes"] = ctx["api_votes"]

    # Normalize
    scores = _normalize_scores(scores)
    best = max(scores.items(), key=lambda kv: kv[1])[0]

    # --- Strong trigger bypass hysteresis (NEW) ---
    total_trig_mass = sum(float(v) for v in (dbg.get("trigger_votes") or {}).values())
    strong_trigger = total_trig_mass >= STRONG_TRIGGER_SUM

    # Hysteresis: keep last if close (unless strong trigger)
    if not strong_trigger and last and last in scores and (scores[best] - scores[last]) < HYST_TAU:
        best = last
        dbg["hysteresis_kept"] = True
    else:
        dbg["hysteresis_kept"] = False
    dbg["strong_trigger_bypass"] = strong_trigger
    dbg["scores"] = scores  # keep normalized scores in debug for logging

    # Clamp to allowed range (with alias)
    allowed = ctx.get("npc_profile", {}).get("emotion_range")
    best = _clamp_to_range(best, allowed)

    style = realize_style(best, ctx.get("npc_profile", {}).get("style_emotion_map"))

    return {
        "emotion_hint": best,
        "style_hooks": style,
        "debug": dbg
    }

# ===============================
# 2) Post-Infer (content-driven)
# ===============================

def post_infer(output_text: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Infer emotion from *self-reported content*.
    Returns: {"emotion_from_content": str|None, "confidence": float, "matches": [...], "debug": {...}}
    """
    labels = _labels(ctx)
    text = _norm(output_text)
    if not text:
        return {"emotion_from_content": None, "confidence": 0.0, "matches": [], "debug": {"raw_scores": _blank_scores(labels)}}

    scores = _blank_scores(labels)
    matches: List[str] = []

    # A) rule matches from content schema
    for key, cfg in _content(ctx).items():
        phrases: List[str] = cfg.get("phrases", [])
        for p in phrases:
            p_l = p.lower()
            if p_l and p_l in text:
                matches.append(p)
                for e, w in (cfg.get("votes") or {}).items():
                    if e in scores:
                        scores[e] += float(w)

    # B) minimal polarity cues (optional)
    pos_cues = ["good", "great", "happy", "glad", "relieved"]
    neg_cues = ["bad", "sad", "angry", "upset", "tired", "problem"]
    if any(c in text for c in pos_cues):
        if "cheerful" in scores: scores["cheerful"] += 0.5
        if "friendly" in scores: scores["friendly"] += 0.3
    if any(c in text for c in neg_cues):
        if "annoyed"  in scores: scores["annoyed"]  += 0.5
        if "sad"      in scores: scores["sad"]      += 0.4
        if "serious"  in scores: scores["serious"]  += 0.2

    # Normalize
    scores = _normalize_scores(scores)
    best = max(scores.items(), key=lambda kv: kv[1])[0]
    conf = scores[best]

    # Clamp (with alias)
    allowed = ctx.get("npc_profile", {}).get("emotion_range")
    best = _clamp_to_range(best, allowed)

    return {
        "emotion_from_content": best,
        "confidence": float(conf),
        "matches": matches,
        "debug": {"raw_scores": scores}
    }

# ==============================
# 3) Style realization (generator)
# ==============================

def realize_style(emotion: str, style_map: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return style hooks for the given emotion with robust fallback."""
    em = EMOTION_ALIASES.get(emotion, emotion) if emotion else "neutral"
    style: Dict[str, Any] = {"prefix": [], "suffix": [], "tone": (em or "neutral")}

    if not isinstance(style_map, dict):
        # Built-in safe defaults (even with no map configured)
        if em == "cheerful":
            return {"prefix": ["Hey,"], "suffix": ["!"], "tone": "bright"}
        if em == "friendly":
            return {"prefix": ["Sure,"], "suffix": [], "tone": "warm"}
        if em == "serious":
            return {"prefix": ["Listen,"], "suffix": ["."], "tone": "flat"}
        return style  # neutral

    # exact match
    m = style_map.get(em)
    if not m:
        # try similarity chain
        for alt in EMOTION_FALLBACK_CHAIN.get(em, []):
            m = style_map.get(alt)
            if m: break
        # last resort
        if not m:
            m = style_map.get("neutral", None)

    if isinstance(m, dict):
        for k in ("prefix", "suffix", "tone"):
            if k in m: style[k] = m[k]
    return style

# ==========================================
# Internal: trigger votes (used in pre phase)
# ==========================================

def _trigger_votes(text: str, ctx: Dict[str, Any]) -> Tuple[Dict[str, float], List[str]]:
    t = _norm(text)
    labels = _labels(ctx)
    votes = _blank_scores(labels)
    hits: List[str] = []
    for key, cfg in _triggers(ctx).items():
        phrases: List[str] = cfg.get("phrases", [])
        for p in phrases:
            p_l = p.lower()
            if p_l and p_l in t:
                hits.append(p)
                for e, w in (cfg.get("votes") or {}).items():
                    if e in votes:
                        votes[e] += float(w)
    return votes, hits

# =====================================================
# Optional helper: propose final emotion in one call
# =====================================================

def propose_emotion(drafted_text: Optional[str], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convenience wrapper:
      1) pre = pre_hint(ctx)
      2) post = post_infer(drafted_text, ctx) if drafted_text else None
      3) final = post.emotion_from_content or pre.emotion_hint
      4) style = realize_style(final, profile.style_emotion_map)
    """
    pre = pre_hint(ctx)
    post = post_infer(drafted_text or "", ctx) if drafted_text is not None else {"emotion_from_content": None, "confidence": 0.0}
    final = post.get("emotion_from_content") or pre["emotion_hint"]
    style = realize_style(final, ctx.get("npc_profile", {}).get("style_emotion_map"))
    return {
        "pre_hint": pre,
        "post_infer": post,
        "final_emotion": final,
        "style_hooks": style
    }

# ===========
# Self-test
# ===========
if __name__ == "__main__":
    ctx = {
        "user_text": "thanks for the help at the gate",
        "npc_id": "guard_01",
        "slot_name": "small_talk",
        "last_emotion": "neutral",
        "npc_profile": {
            "baseline_emotion": "serious",
            "emotion_range": DEFAULT_SCHEMA["labels"],
            "speaking_style": "formal, brief",
            "style_emotion_map": {
                "cheerful": {"prefix": ["Hey,"], "suffix": ["!"], "tone": "bright"},
                "serious":  {"prefix": ["Listen,"], "suffix": ["."], "tone": "flat"},
                "neutral":  {"tone": "neutral"}
            }
        },
        "emotion_schema": DEFAULT_SCHEMA
    }

    print("=== PRE-HINT ===")
    pre = pre_hint(ctx); print(pre)

    draft = "I got off early today and I'm taking it easy."
    print("=== POST-INFER (content-driven) ===")
    post = post_infer(draft, ctx); print(post)

    final_emotion = post.get("emotion_from_content") or pre["emotion_hint"]
    style = realize_style(final_emotion, ctx["npc_profile"]["style_emotion_map"])
    print("=== STYLE HOOKS ==="); print(style)
