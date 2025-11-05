# -*- coding: utf-8 -*-
"""
retriever.py — minimal, drop-in normalized retriever

功能：
- 统一规范化用户输入与证据文本，避免大小写/标点导致 must/forbid 误判。
- 严格 AND：有 must 且 require_slot_must=True 时，必须全部命中。
- forbid 命中（用户侧或证据侧）直接判不足。
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Iterable
import re

# --------------------------
# Text processing utilities
# --------------------------
_STOP = set("""
a an the and or but if while of in on at by for to from with without into onto over under as is are was were be been being
this that these those here there it its they them he she we you i me my your his her our their
how what when where who which whose why whether
do does did done doing have has had having get got getting make makes made making
not no nor only just also too very much more most less least
can could may might must shall should will would
s am re ve ll d
""".split())

def _canon(s: Optional[str]) -> str:
    t = (s or "").lower()
    t = t.replace("_", " ")
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

def _tok(s: str) -> List[str]:
    t = _canon(s)
    toks = t.split()
    # 若疑似中文/无空格文本：退化为 2-gram
    if len(toks) <= 1 and len(t) > 4:
        return [t[i:i+2] for i in range(len(t)-1)]
    return toks

def _filter_tokens(toks: Iterable[str]) -> List[str]:
    out = []
    for w in toks:
        if len(w) <= 1:  # 去除极短
            continue
        if w in _STOP:
            continue
        # 极简词干（不依赖外部库）
        for suf in ("ing","ed","es","s"):
            if len(w) > len(suf)+2 and w.endswith(suf):
                w = w[:-len(suf)]
                break
        out.append(w)
    return out

def _row_blob(row: Dict[str, Any]) -> str:
    fact = str(row.get("fact", "") or "")
    entity = str(row.get("entity", "") or "")
    tags = row.get("tags", [])
    if isinstance(tags, list):
        tags_txt = " ".join(str(x) for x in tags)
    else:
        tags_txt = str(tags or "").replace(";", ",")
    blob_raw = " ".join([fact, entity, tags_txt])
    return _canon(blob_raw)

# --------------------------
# Main retrieval function
# --------------------------
def retrieve_public_evidence(
    user_text: str,
    npc_id: Optional[str] = None,
    slot_hints: Optional[Dict[str, Any]] = None,
    slot_name: Optional[str] = None,
    require_slot_must: bool = True,
    compiled_lore_public: Optional[List[Dict[str, Any]]] = None,
    max_evidence: int = 5,
) -> Dict[str, Any]:
    slot_hints = slot_hints or {}
    must_list   = [_canon(x) for x in (slot_hints.get("must") or []) if str(x).strip()]
    forbid_list = [_canon(x) for x in (slot_hints.get("forbid") or []) if str(x).strip()]
    pool = compiled_lore_public or []

    user_norm = _canon(user_text)
    user_words = set(_filter_tokens(_tok(user_norm)))  # 对用户词汇也进行过滤

    # forbid（用户侧）
    if any(f and f in user_norm for f in forbid_list):
        return {
            "flags": {"insufficient": True},
            "evidence": [],
            "audit": {"must": must_list, "forbid": forbid_list, "reason": "forbid_user"},
        }

    scored_evidence: List[tuple[int, Dict[str, Any]]] = []
    
    for row in pool:
        blob = _row_blob(row)
        blob_words = set(_filter_tokens(_tok(blob)))  # 对证据词汇也进行过滤

        # forbid（证据侧）- 跳过禁止的证据
        if any(f and f in blob for f in forbid_list):
            continue

        # must 命中（或无 must 要求）
        if (not must_list) or all(m and m in blob for m in must_list):
            # 计算相关性分数 - 使用过滤后的词汇
            common_words = user_words & blob_words
            score = len(common_words)
            
            # 实体名称匹配额外加分
            entity = str(row.get("entity", "")).strip().lower()
            if entity and any(entity in word for word in user_words):
                score += 3
            
            # 只有在有must条件或分数>0时才保留证据
            if must_list or score > 0:
                scored_evidence.append((score, row))

    # 按相关性分数排序
    scored_evidence.sort(key=lambda x: x[0], reverse=True)
    picked = [row for score, row in scored_evidence]

    # 如果没有must条件且没有相关证据，返回证据不足
    if not must_list and not picked:
        return {
            "flags": {"insufficient": True},
            "evidence": [],
            "audit": {"must": must_list, "forbid": forbid_list, "reason": "no_relevant_evidence"},
        }

    # 严格模式：有 must 但未命中 ⇒ 不足
    if require_slot_must and must_list and not picked:
        return {
            "flags": {"insufficient": True},
            "evidence": [],
            "audit": {"must": must_list, "forbid": forbid_list, "reason": "must_not_met"},
        }

    # 正常返回
    return {
        "flags": {"insufficient": len(picked) == 0},
        "evidence": picked[:max_evidence],
        "audit": {"must": must_list, "forbid": forbid_list},
    }