
from __future__ import annotations
from typing import List, Dict, Any
import json
from pathlib import Path

CACHE = Path(__file__).resolve().parent / ".cache" / "compiled.json"

def _load_cache() -> Dict[str, Any]:
    return json.loads(CACHE.read_text(encoding="utf-8"))

def simple_score(query: str, fact: Dict[str, Any]) -> int:
    q = set(query.lower().split())
    f = set((fact["fact"] + " " + fact["entity"]).lower().split())
    return len(q & f)

def retrieve_public_topk(query: str, required_tags: List[str], forbidden_tags: List[str], k: int = 3) -> List[Dict[str, Any]]:
    cache = _load_cache()
    evidence_index = cache["evidence_index"]
    cand = []
    for t in required_tags or []:
        for fact in evidence_index.get(t, []):
            if fact["visibility"] != "public":
                continue
            cand.append(fact)
    dedup = {f["fact_id"]: f for f in cand}
    scored = sorted(dedup.values(), key=lambda f: simple_score(query, f), reverse=True)
    return scored[:k]
