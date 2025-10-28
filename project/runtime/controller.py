
from __future__ import annotations
from typing import Dict, Any, List
import csv, json
from pathlib import Path

from .validators import parse_json_list_forgiving
from .retriever import retrieve_public_topk
from .filters import npc_whitelist, taboo_block
from .emotion_engine import fuse_emotion

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

SLOT_REQUIRED = {
    "greeting":    ["city"],
    "quest_hint":  ["city", "events"],
    "shop_advice": ["trade", "items"],
    "directions":  ["city"],
    "law_info":    ["law"],
}
SLOT_FORBIDDEN = {
    "greeting":    ["secret", "rumor"],
    "quest_hint":  ["secret", "security"],
    "directions":  ["secret"],
    "law_info":    ["secret"],
}

def load_first_npc() -> Dict[str, Any]:
    rows = list(csv.DictReader((DATA / "npc.csv").open("r", encoding="utf-8")))
    if not rows:
        raise RuntimeError("No NPC in data/npc.csv")
    r = rows[0]
    r["allowed_tags_list"] = parse_json_list_forgiving(r["allowed_tags"])
    r["taboo_topics_list"] = parse_json_list_forgiving(r["taboo_topics"])
    return r

def run_pipeline(user_text: str, slot_id: str, k: int = 3) -> Dict[str, Any]:
    npc = load_first_npc()

    if taboo_block(npc, user_text):
        return {"blocked": True, "reason": "taboo_topic", "npc_id": npc["npc_id"]}

    if slot_id == "past_story":
        facts = []
        allow_improvise = True
    else:
        req = SLOT_REQUIRED.get(slot_id, ["city"])
        forbd = SLOT_FORBIDDEN.get(slot_id, [])
        facts = retrieve_public_topk(user_text, required_tags=req, forbidden_tags=forbd, k=k)
        facts = npc_whitelist(npc, facts)
        allow_improvise = False

    baseline = npc["baseline_emotion"]
    emotion = fuse_emotion(baseline=baseline, prev=baseline, user_text=user_text)

    return {
        "npc": {"id": npc["npc_id"], "name": npc["name"], "role": npc["role"]},
        "slot_id": slot_id,
        "emotion": emotion,
        "facts": facts,
        "allow_improvise": allow_improvise,
        "safety": {"denial_template": npc["denial_template"]},
        "plan": f"{'即兴优先' if allow_improvise else '证据优先'} · tone={emotion} · slot={slot_id} · facts={len(facts)}",
    }
