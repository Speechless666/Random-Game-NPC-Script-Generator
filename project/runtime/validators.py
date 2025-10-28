from __future__ import annotations
import json
from typing import Any, Dict, List, Set

VIS_SET = {"public", "secret"}

class ValidationError(Exception):
    pass

def parse_json_list_forgiving(value: str) -> List[str]:
    '''
    Accepts:
      - Proper JSON list string: ["a","b"]
      - Human list: a, b, c  (normalized to list of strings)
    '''
    s = (value or "").strip()
    if not s:
        return []
    # Try strict JSON first
    try:
        v = json.loads(s)
        if isinstance(v, list):
            return [str(x).strip() for x in v]
    except Exception:
        pass

    # Human-friendly: split by commas
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    parts = [p.strip() for p in s.split(",")]
    out = []
    for p in parts:
        if not p:
            continue
        p = p.strip().strip('"').strip("'")
        if p:
            out.append(p)
    if not out:
        raise ValidationError(f"Expected list (JSON or 'a, b, c'), got: {value!r}")
    return out

def parse_kv_map_forgiving(value: str) -> Dict[str, str]:
    '''
    Accepts:
      - Proper JSON object string: {"k":"v","k2":"v2"}
      - Human map: k: v; k2: v2
      - Or: k: v, k2: v2
    Returns a dict[str,str].
    '''
    s = (value or "").strip()
    if not s:
        return {}

    # Try strict JSON first
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return {str(k): str(v) for k, v in obj.items()}
    except Exception:
        pass

    # Human-friendly parse
    # Prefer ';' as pair separator; otherwise fallback to ','
    sep = ";" if ";" in s else ","
    pairs = [p.strip() for p in s.split(sep)]
    kv: Dict[str, str] = {}
    for pair in pairs:
        if not pair:
            continue
        if ":" not in pair:
            # Skip fragments that don't look like k: v
            continue
        k, v = pair.split(":", 1)
        k = k.strip().strip('"').strip("'")
        v = v.strip().strip('"').strip("'")
        if k:
            kv[k] = v
    if not kv:
        raise ValidationError(f"Expected JSON object or 'k: v; k2: v2', got: {value!r}")
    return kv

class Validators:
    def __init__(self, emotion_schema: Dict[str, Any], slots: Dict[str, Any]):
        self.emotions: Set[str] = set(emotion_schema.get("emotions", []))
        self.transforms: Dict[str, List[str]] = emotion_schema.get("transforms", {})
        self.allowed_transitions: Dict[str, List[str]] = emotion_schema.get("allowed_transitions", {})
        self.slot_ids: Set[str] = {s["id"] for s in slots.get("slots", [])}
        self.slot_all_tags: Set[str] = set()
        for s in slots.get("slots", []):
            self.slot_all_tags.update(s.get("must", []))
            self.slot_all_tags.update(s.get("forbid", []))

    def _ensure(self, cond: bool, msg: str):
        if not cond:
            raise ValidationError(msg)

    def emotion_ok(self, emo: str):
        return (emo in self.emotions) or any(emo in alts for alts in self.transforms.values())

    def validate_npc_row(self, row: Dict[str, Any]):
        required = [
            "npc_id","name","role","baseline_emotion","emotion_range",
            "style_emotion_map","speaking_style","taboo_topics","allowed_tags","denial_template"
        ]
        for k in required:
            self._ensure(row.get(k) not in (None, ""), f"npc.{row.get('npc_id')} missing field: {k}")

        be = (row["baseline_emotion"] or "").strip()
        self._ensure(self.emotion_ok(be), f"npc.{row['npc_id']} illegal emotion: {be}")

        er = set(parse_json_list_forgiving(row["emotion_range"]))
        self._ensure(all(self.emotion_ok(e) for e in er), f"npc.{row['npc_id']} emotion_range contains illegal emotions")

        # style_emotion_map: try JSON; fallback to human-friendly "k: v; k2: v2"
        try:
            sem = json.loads(row["style_emotion_map"])
            if not isinstance(sem, dict):
                raise TypeError("not a dict")
        except Exception:
            sem = parse_kv_map_forgiving(row["style_emotion_map"])

        self._ensure(set(sem.keys()).issubset(er | {be}),
                     "style_emotion_map keys must be in emotion_range or baseline_emotion")

        # allowed_tags / taboo_topics accept "a, b, c"
        at = set(parse_json_list_forgiving(row["allowed_tags"]))
        self._ensure(len(at) > 0, "allowed_tags should not be empty")
        _ = parse_json_list_forgiving(row["taboo_topics"])  # just to normalize/validate

    def validate_lore_row(self, row: Dict[str, Any]):
        required = ["fact_id","entity","fact","tags","visibility"]
        for k in required:
            self._ensure(row.get(k) not in (None, ""), f"lore.{row.get('fact_id')} missing field: {k}")
        self._ensure(row["visibility"] in VIS_SET, f"lore.{row['fact_id']} visibility must be public/secret")
        _ = parse_json_list_forgiving(row["tags"])

    def validate_slots(self, slots: Dict[str, Any]):
        for s in slots.get("slots", []):
            sid = s.get("id")
            self._ensure(sid, "slot missing id")
            for fld in ("must","forbid","tone_guidelines"):
                self._ensure(fld in s, f"slot.{sid} missing field {fld}")
            must = set(s.get("must", []))
            forbid = set(s.get("forbid", []))
            self._ensure(must.isdisjoint(forbid), f"slot.{sid} has overlapping must/forbid")
            tg = s.get("tone_guidelines", {})
            self._ensure(all(self.emotion_ok(k) for k in tg.keys()), f"slot.{sid} tone_guidelines contains illegal emotion keys")

    def cross_validate(self, npcs, lore):
        lore_tags: Set[str] = set()
        for r in lore:
            lore_tags.update(parse_json_list_forgiving(r["tags"]))
        for r in npcs:
            at = set(parse_json_list_forgiving(r["allowed_tags"]))
            self._ensure(at.issubset(lore_tags), f"npc.{r['npc_id']} allowed_tags contain unknown tags: {at - lore_tags}")