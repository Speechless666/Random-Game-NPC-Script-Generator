# -*- coding: utf-8 -*-
"""
retriever.py — minimal, drop-in normalized retriever

功能：
- 在不改变外部接口/返回格式的前提下，统一对用户输入和证据文本做“轻量规范化”
  （小写、去标点、压空白），避免因标点/大小写造成的 must/forbid 误判。
- 不引入词典、词干、向量等复杂逻辑；严格 AND 语义保持不变。
- 证据格式兼容：每条记录包含 fact / entity / tags（tags 可为 list 或 str）。

典型用法（与之前一致）：
    r = retrieve_public_evidence(
        user_text="what's new in the market?",
        npc_id="S001",
        slot_hints={"must": ["market"], "forbid": []},
        slot_name="market_query",
        require_slot_must=True,
        compiled_lore_public=LORE_PUBLIC,   # list[dict], 每条有 fact/entity/tags
    )

返回示例：
{
  "flags": {"insufficient": False},
  "evidence": [ ... up to 5 rows ... ],
  "audit": {"must": ["market"], "forbid": []}
}
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional
import re

# --------------------------
# 轻量规范化工具
# --------------------------

def _canon(s: Optional[str]) -> str:
    """
    小写、去标点、压空白。
    例："what's new in the market?" -> "what s new in the market"
    """
    t = (s or "").lower()
    t = t.replace("_", " ")              # 新增：下划线当空格
    t = re.sub(r"[^\w\s]", " ", t)       # 非字母数字下划线/空白 → 空格
    t = re.sub(r"\s+", " ", t).strip()  # 压缩空白
    return t

def _row_blob(row: Dict[str, Any]) -> str:
    """
    将一条 lore 记录的可检索字段拼成文本块，并做规范化。
    兼容 tags 为 list 或 str。
    """
    fact = str(row.get("fact", "") or "")
    entity = str(row.get("entity", "") or "")
    tags = row.get("tags", [])
    if isinstance(tags, list):
        tags_txt = " ".join(str(x) for x in tags)
    else:
        # 兼容 "city, trade" 或 "city; trade"
        tags_txt = str(tags or "").replace(";", ",")
    blob_raw = " ".join([fact, entity, tags_txt])
    return _canon(blob_raw)

# --------------------------
# 主入口（与原项目签名保持一致）
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
    """
    仅做最小必要修复：统一规范化后再做 must/forbid 的包含判定与证据筛选。
    - 不改变严格 AND 的设定：有 must 且 require_slot_must=True 时，必须全部命中。
    - forbid 命中（用户侧或证据侧）直接判不足。
    - 证据最多返回前 max_evidence 条（维持稳定性）。
    """
    slot_hints = slot_hints or {}
    must_list   = [_canon(x) for x in (slot_hints.get("must") or []) if str(x).strip()]
    forbid_list = [_canon(x) for x in (slot_hints.get("forbid") or []) if str(x).strip()]
    pool = compiled_lore_public or []

    user_norm = _canon(user_text)

    # 1) 用户侧 forbid 命中：直接不足（更严格）
    if any(f and f in user_norm for f in forbid_list):
        return {
            "flags": {"insufficient": True},
            "evidence": [],
            "audit": {"must": must_list, "forbid": forbid_list, "reason": "forbid_user"},
        }

    # 2) 遍历证据（规范化后再比较）
    picked: List[Dict[str, Any]] = []
    for row in pool:
        blob = _row_blob(row)

        # 证据侧 forbid 命中：直接不足（避免输出“脏证据”）
        if any(f and f in blob for f in forbid_list):
            return {
                "flags": {"insufficient": True},
                "evidence": [],
                "audit": {"must": must_list, "forbid": forbid_list, "reason": "forbid_evidence"},
            }

        # 满足 must（或不存在 must 要求）则收集
        if (not must_list) or all(m and m in blob for m in must_list):
            picked.append(row)

    # 3) 严格模式：有 must 但未命中 ⇒ 不足
    if require_slot_must and must_list and not picked:
        return {
            "flags": {"insufficient": True},
            "evidence": [],
            "audit": {"must": must_list, "forbid": forbid_list, "reason": "must_not_met"},
        }

    # 4) 正常返回（最多前 max_evidence 条）
    return {
        "flags": {"insufficient": len(picked) == 0},
        "evidence": picked[:max_evidence],
        "audit": {"must": must_list, "forbid": forbid_list},
    }

# --------------------------
# 自测（可选）：直接运行本文件
# --------------------------

if __name__ == "__main__":
    # 简单内置样例，便于快速验证“market?” 能通过 must=["market"] 的检查
    LORE_PUBLIC = [
        {"fact_id": "L004", "entity": "East Gate",     "tags": "city, trade", "fact": "Closest gate to the riverfront market."},
        {"fact_id": "L006", "entity": "Market Square", "tags": "city, trade", "fact": "Vendors peak around midday; quiet after dusk."},
        {"fact_id": "L010", "entity": "Guild Hall",    "tags": "guild, admin", "fact": "Public notices are posted weekly."},
    ]

    tests = [
        {
            "desc": "market? 应命中 must=market",
            "args": {
                "user_text": "what's new in the market?",
                "npc_id": "S001",
                "slot_hints": {"must": ["market"], "forbid": []},
                "slot_name": "market_query",
                "require_slot_must": True,
                "compiled_lore_public": LORE_PUBLIC,
            },
        },
        {
            "desc": "marketplace? 仍旧需要更高级的模糊匹配（本最小补丁不覆盖）",
            "args": {
                "user_text": "any news from the marketplace?",
                "npc_id": "S001",
                "slot_hints": {"must": ["market"], "forbid": []},
                "slot_name": "market_query",
                "require_slot_must": True,
                "compiled_lore_public": LORE_PUBLIC,
            },
        },
        {
            "desc": "forbid（用户侧）命中",
            "args": {
                "user_text": "where's the black market tonight?",
                "npc_id": "S001",
                "slot_hints": {"must": ["market"], "forbid": ["black_market"]},
                "slot_name": "market_query",
                "require_slot_must": True,
                "compiled_lore_public": LORE_PUBLIC,
            },
        },
    ]

    for t in tests:
        print("\n---", t["desc"], "---")
        res = retrieve_public_evidence(**t["args"])
        from pprint import pprint
        pprint(res)
