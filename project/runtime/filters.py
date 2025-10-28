
from __future__ import annotations
from typing import Dict, Any, List
import json
from pathlib import Path

CACHE = Path(__file__).resolve().parent / ".cache" / "compiled.json"

def _load_cache() -> Dict[str, Any]:
    return json.loads(CACHE.read_text(encoding="utf-8"))

def npc_whitelist(npc_row: Dict[str, Any], facts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cache = _load_cache()
    allowed_entities = set(cache["allowed_entities"])
    return [f for f in facts if f["entity"] in allowed_entities]

def taboo_block(npc_row: Dict[str, Any], user_text: str) -> bool:
    taboo = (npc_row.get("taboo_topics") or "")
    taboo = taboo.strip().strip("[]")
    toks = [t.strip().strip('"').strip("'").lower() for t in taboo.split(",") if t.strip()]
    text = (user_text or "").lower()
    return any(tok and tok in text for tok in toks)
