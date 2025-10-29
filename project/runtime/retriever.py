# -*- coding: utf-8 -*-
"""
retriever.py — minimal, drop-in normalized retriever

功能：
- 统一规范化用户输入与证据文本，避免大小写/标点导致 must/forbid 误判。
- 严格 AND：有 must 且 require_slot_must=True 时，必须全部命中。
- forbid 命中（用户侧或证据侧）直接判不足。
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional
import re

def _canon(s: Optional[str]) -> str:
    t = (s or "").lower()
    t = t.replace("_", " ")
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

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

    # forbid（用户侧）
    if any(f and f in user_norm for f in forbid_list):
        return {
            "flags": {"insufficient": True},
            "evidence": [],
            "audit": {"must": must_list, "forbid": forbid_list, "reason": "forbid_user"},
        }

    picked: List[Dict[str, Any]] = []
    for row in pool:
        blob = _row_blob(row)

        # forbid（证据侧）
        if any(f and f in blob for f in forbid_list):
            return {
                "flags": {"insufficient": True},
                "evidence": [],
                "audit": {"must": must_list, "forbid": forbid_list, "reason": "forbid_evidence"},
            }

        # must 命中（或无 must 要求）
        if (not must_list) or all(m and m in blob for m in must_list):
            picked.append(row)

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
