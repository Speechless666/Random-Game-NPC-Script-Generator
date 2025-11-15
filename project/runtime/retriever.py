# -*- coding: utf-8 -*-
"""
retriever.py — minimal, drop-in normalized retriever
(MODIFIED: Fixed return bug in _canon)
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Iterable
import re
import pandas as pd
from pathlib import Path

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
    # --- THIS IS THE FIX ---
    return t
    # --- END FIX ---

def _tok(s: str) -> List[str]:
    t = _canon(s)
    toks = t.split()
    if len(toks) <= 1 and len(t) > 4:
        return [t[i:i+2] for i in range(len(t)-1)]
    return toks

def _filter_tokens(toks: Iterable[str]) -> List[str]:
    out = []
    for w in toks:
        if len(w) <= 1:
            continue
        if w in _STOP:
            continue
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

# (All other functions remain as they were in the previously modified file)

def retrieve_relevant_memory(
    user_text: str, npc_id: str,
    memory_path: str, # This path is now USED
    config: Dict[str, Any],
    max_memory_override: Optional[int] = None,
    min_score_override: Optional[float] = None
) -> List[Dict[str, Any]]:

    thresh = config.get('thresholds', {})
    max_memory = max_memory_override if max_memory_override is not None else thresh.get('retriever_mem_max', 5)
    min_score = min_score_override if min_score_override is not None else thresh.get('retriever_mem_min_score', 2.0)
    min_user_words = thresh.get('retriever_mem_min_user_words', 2)
    user_coverage_weight = thresh.get('retriever_mem_user_weight', 3.0)
    mem_coverage_weight = thresh.get('retriever_mem_mem_weight', 2.0)
    
    try:
        df_memory = pd.read_csv(memory_path)
    except FileNotFoundError:
        print(f"Long-term memory file not found: {memory_path}")
        return []

    user_norm = _canon(user_text)
    user_words = set(_filter_tokens(_tok(user_norm)))
    
    if len(user_words) < min_user_words:
        return []

    relevant_memories = []

    for _, row in df_memory.iterrows():
        if str(row.get("npc_id")) != str(npc_id):
            continue
            
        memory_blob = _row_blob(row)
        memory_words = set(_filter_tokens(_tok(memory_blob)))
        
        common_words = user_words & memory_words
        if not common_words:
            continue
            
        score = 0
        base_score = len(common_words)
        user_coverage = len(common_words) / len(user_words) if user_words else 0
        memory_coverage = len(common_words) / len(memory_words) if memory_words else 0
        
        score = base_score
        coverage_bonus = min(user_coverage * user_coverage_weight, memory_coverage * mem_coverage_weight)
        score += coverage_bonus
        
        if score >= min_score:
            row_dict = row.to_dict()
            row_dict['relevance_score'] = score
            row_dict['match_details'] = {
                'common_words': list(common_words),
                'user_coverage': user_coverage,
                'memory_coverage': memory_coverage
            }
            relevant_memories.append(row_dict)

    relevant_memories.sort(key=lambda x: x['relevance_score'], reverse=True)
    
    return [{'memory': mem["fact"] for mem in relevant_memories[:max_memory]}]

# --------------------------
# Main retrieval function
# --------------------------
def retrieve_public_evidence(
    user_text: str,
    config: Dict[str, Any],         # <-- ADDED
    memory_path: str,             # <-- ADDED
    npc_id: Optional[str] = None,
    slot_hints: Optional[Dict[str, Any]] = None,
    slot_name: Optional[str] = None,
    require_slot_must: bool = True,
    compiled_lore_public: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:

    thresh = config.get('thresholds', {})
    max_evidence = thresh.get('retriever_lore_max', 5)
    entity_bonus = thresh.get('retriever_lore_entity_bonus', 3)
    longterm_max = thresh.get('retriever_lore_mem_max', 3)
    longterm_min_score = thresh.get('retriever_lore_mem_min_score', 1.5)

    slot_hints = slot_hints or {}
    must_list   = [_canon(x) for x in (slot_hints.get("must") or []) if str(x).strip()]
    forbid_list = [_canon(x) for x in (slot_hints.get("forbid") or []) if str(x).strip()]
    pool = compiled_lore_public or []

    user_norm = _canon(user_text)
    user_words = set(_filter_tokens(_tok(user_norm)))

    if any(f and f in user_norm for f in forbid_list):
        return {
            "flags": {"insufficient": True},
            "evidence": [],
            "audit": {"must": must_list, "forbid": forbid_list, "reason": "forbid_user"},
        }

    scored_evidence: List[tuple[int, Dict[str, Any]]] = []
    
    for row in pool:
        blob = _row_blob(row)
        blob_words = set(_filter_tokens(_tok(blob)))

        if any(f and f in blob for f in forbid_list):
            continue

        if (not must_list) or all(m and m in blob for m in must_list):
            common_words = user_words & blob_words
            score = len(common_words)
            
            entity = str(row.get("entity", "")).strip().lower()
            if entity and any(entity in word for word in user_words):
                score += entity_bonus
            
            if must_list or score > 0:
                scored_evidence.append((score, row))

    scored_evidence.sort(key=lambda x: x[0], reverse=True)
    picked = [row for score, row in scored_evidence]
    
    if npc_id:
        long_term_memories = retrieve_relevant_memory(
            user_text, npc_id, 
            memory_path=memory_path, 
            config=config,
            max_memory_override=longterm_max,
            min_score_override=longterm_min_score
        )
        picked = long_term_memories + picked
    
    if not must_list and not picked:
        return {
            "flags": {"insufficient": True},
            "evidence": [],
            "audit": {"must": must_list, "forbid": forbid_list, "reason": "no_relevant_evidence"},
        }

    if require_slot_must and must_list and not picked:
        return {
            "flags": {"insufficient": True},
            "evidence": [],
            "audit": {"must": must_list, "forbid": forbid_list, "reason": "must_not_met"},
        }

    return {
        "flags": {"insufficient": len(picked) == 0},
        "evidence": picked[:max_evidence],
        "audit": {"must": must_list, "forbid": forbid_list},
    }