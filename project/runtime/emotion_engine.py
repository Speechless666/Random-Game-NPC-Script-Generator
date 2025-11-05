# -*- coding: utf-8 -*-
"""
emotion_engine.py — Phase 2 · Emotion & Style (Two-step: Pre-Hint → Post-Align)

不生成自然语言，仅输出：
  1) pre_hint(ctx):  生成前的"弱情绪提示 + 样式钩子"
  2) post_infer(...): 直接使用模型提供的情绪标签，只做简单验证
  3) realize_style(...): 情绪 → 样式钩子映射
"""

from __future__ import annotations
from typing import Dict, Any, List, Tuple, Optional
import re

# ==================
# Tunable weights（保持原数值）
# ==================
W_BASE   = 0.20
W_SLOT   = 0.15
W_TRIG   = 0.50
W_INERT  = 0.10
W_API    = 0.00
HYST_TAU = 0.25
STRONG_TRIGGER_SUM = 0.90

_WORD = re.compile(r"[a-zA-Z']+")

# ==========================
# Emotion aliases & fallback（不改）
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
# 默认 schema（仅保留 labels/tone_map；清空 demo triggers/content）
# ==========================
DEFAULT_SCHEMA: Dict[str, Any] = {
    "labels": ["neutral", "friendly", "cheerful", "serious", "annoyed", "sad"],
    "tone_map": {
        "serious":  {"serious": 0.6, "neutral": 0.4},
        "friendly": {"friendly": 0.6, "cheerful": 0.4},
        "formal":   {"serious": 0.5, "neutral": 0.5},
        "casual":   {"friendly": 0.5, "cheerful": 0.5}
    },
    "triggers": {},   # ← 清空 demo
    "content":  {},   # ← 清空 demo
}

# =============
# Util helpers（不改）
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

def _clamp_to_range(emotion: str, allowed: Any, original_scores: Dict[str, float] = None) -> str:
    """将情绪钳制到NPC允许的范围内 - 基于原始得分权重"""
    if not allowed:
        return emotion
    
    # 规范化输入情绪
    em = EMOTION_ALIASES.get(emotion, emotion).lower()
    
    # 处理 allowed 的各种格式
    if isinstance(allowed, str):
        allowed_emotions = [e.strip().lower() for e in allowed.split(',')]
    elif isinstance(allowed, list):
        allowed_emotions = [e.lower() if isinstance(e, str) else str(e) for e in allowed]
    else:
        return em
    
    # 检查情绪是否在允许范围内
    if em in allowed_emotions:
        return em
    else:
        # 不在范围内，选择允许范围内原始得分最高的情绪
        if original_scores:
            allowed_with_scores = [(e, original_scores.get(e, 0)) for e in allowed_emotions if e in original_scores]
            if allowed_with_scores:
                return max(allowed_with_scores, key=lambda x: x[1])[0]
        
        # 如果没有得分信息或没有匹配的得分，返回第一个允许的情绪
        return allowed_emotions[0] if allowed_emotions else "neutral"

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
# 1) Pre-Hint（不改逻辑）
# ==========================
def pre_hint(ctx: Dict[str, Any]) -> Dict[str, Any]:
    labels = _labels(ctx)
    scores = _blank_scores(labels)
    dbg: Dict[str, Any] = {}

    base_em = _norm(ctx.get("npc_profile", {}).get("baseline_emotion"))
    if base_em and base_em in scores:
        scores[base_em] += W_BASE
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
        _mix_into(scores, slot_bias_map, W_SLOT)
    dbg["slot_prior"] = slot_bias_map

    trig_votes, trig_hits = _trigger_votes(ctx.get("user_text") or "", ctx)
    _mix_into(scores, trig_votes, W_TRIG)
    dbg["trigger_hits"] = trig_hits
    dbg["trigger_votes"] = trig_votes

    last = _norm(ctx.get("last_emotion"))
    if last and last in scores:
        scores[last] += W_INERT
    dbg["last_emotion"] = last or None

    if W_API > 0.0 and isinstance(ctx.get("api_votes"), dict):
        _mix_into(scores, ctx["api_votes"], W_API)
        dbg["api_votes"] = ctx["api_votes"]

    scores = _normalize_scores(scores)
    best = max(scores.items(), key=lambda kv: kv[1])[0]

    total_trig_mass = sum(float(v) for v in (dbg.get("trigger_votes") or {}).values())
    strong_trigger = total_trig_mass >= STRONG_TRIGGER_SUM

    if not strong_trigger and last and last in scores and (scores[best] - scores[last]) < HYST_TAU:
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
# 2) Post-Infer（简化版本，直接使用模型情绪）
# ===============================
def post_infer(output_text: str, draft_emotion: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    直接使用模型提供的情绪标签，只做简单验证和置信度评估
    """
    labels = _labels(ctx)
    
    # 直接使用草稿的情绪标签
    emotion_from_content = draft_emotion
    
    # 计算置信度（基于文本长度、标点等简单启发式）
    confidence = _calculate_confidence_based_on_content(output_text)
    
    return {
        "emotion_from_content": emotion_from_content,
        "confidence": confidence,
        "matches": [],  # 不再需要关键词匹配
        "debug": {
            "source": "draft_emotion",
            "raw_scores": {emotion_from_content: 1.0},  # 简化
            "confidence_factors": confidence
        }
    }

def _calculate_confidence_based_on_content(text: str) -> float:
    """
    基于文本内容计算情绪置信度的简单启发式方法
    """
    if not text:
        return 0.0
    
    # 基础置信度
    confidence = 0.7
    
    # 文本长度因素
    word_count = len(text.split())
    if word_count >= 10:
        confidence += 0.1
    elif word_count <= 3:
        confidence -= 0.2
    
    # 标点符号因素
    if "!" in text:
        confidence += 0.1  # 感叹号通常表示强烈情绪
    if "?" in text and text.count("?") > 1:
        confidence += 0.1  # 多个问号可能表示强烈情绪
    
    # 确保置信度在合理范围内
    return max(0.3, min(0.95, confidence))

# ==============================
# 3) Style realization（不改逻辑）
# ==============================
def realize_style(emotion: str, style_map: Optional[Dict[str, Any]]) -> Dict[str, Any]:
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
# Internal: trigger votes（不改逻辑；只是依赖上游 schema）
# ==========================================
def _trigger_votes(text: str, ctx: Dict[str, Any]) -> Tuple[Dict[str, float], List[str]]:
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