
from __future__ import annotations
from typing import Dict, Any
import json
from pathlib import Path

CACHE = Path(__file__).resolve().parent / ".cache" / "compiled.json"

TRIGGERS = {
    "please": {"friendly": 1},
    "thank": {"friendly": 1},
    "help": {"friendly": 1},
    "hurry": {"serious": 1},
    "urgent": {"serious": 1},
    "bribe": {"annoyed": 1},
    "insult": {"annoyed": 2},
    "festival": {"cheerful": 1},
}

def _load_cache() -> Dict[str, Any]:
    return json.loads(CACHE.read_text(encoding="utf-8"))

def fuse_emotion(baseline: str, prev: str, user_text: str, inertia: float = 0.6) -> str:
    """
    Minimal fusion: baseline + trigger + inertia smoothing.
    - Map triggers to a target emotion; if multiple fire, pick highest weight.
    - Apply inertia: prefer prev unless strong trigger present.
    """
    cache = _load_cache()
    allowed = set(cache["emotion_schema"]["emotions"])

    text = (user_text or "").lower()
    scores = {}
    for kw, delta in TRIGGERS.items():
        if kw in text:
            for emo, w in delta.items():
                scores[emo] = scores.get(emo, 0) + w

    if not scores:
        return prev if inertia > 0.5 else baseline

    emo = max((e for e in scores if e in allowed), key=lambda e: scores[e], default=prev or baseline)

    if prev and prev in allowed and scores.get(emo, 0) < 2 and inertia >= 0.5:
        return prev
    return emo if emo in allowed else baseline
