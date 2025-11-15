from __future__ import annotations
import json
from typing import Any, Dict, List, Set

EMOTION_SCHEMA_OPTIONAL_KEYS = {"labels", "triggers", "content", "tone_map"}

def validate_emotion_schema(doc: Dict[str, Any]) -> None:
    """Allow runtime optional keys to exist without raising errors.
    Keep your original mandatory checks elsewhere (if any)."""
    if not isinstance(doc, dict):
        raise ValidationError("emotion_schema must be a mapping")
    # Merely access these keys to signal 'allowed to exist'
    for k in EMOTION_SCHEMA_OPTIONAL_KEYS:
        _ = doc.get(k, None)

# --- REMOVED: Global VIS_SET = {"public", "secret"} ---
# (This will now be loaded from config)

class ValidationError(Exception):
    pass

def parse_json_list_forgiving(value: str) -> List[str]:
    '''
    (Logic Unchanged)
    '''
    s = (value or "").strip()
    if not s:
        return []
    try:
        v = json.loads(s)
        if isinstance(v, list):
            return [str(x).strip() for x in v]
    except Exception:
        pass
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
    (Logic Unchanged)
    '''
    s = (value or "").strip()
    if not s:
        return {}
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return {str(k): str(v) for k, v in obj.items()}
    except Exception:
        pass
    sep = ";" if ";" in s else ","
    pairs = [p.strip() for p in s.split(sep)]
    kv: Dict[str, str] = {}
    for pair in pairs:
        if not pair:
            continue
        if ":" not in pair:
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
    # --- MODIFIED: __init__ now accepts config ---
    def __init__(self, config: Dict[str, Any], emotion_schema: Dict[str, Any], slots: Dict[str, Any]):
        # (Original logic unchanged)
        self.emotions: Set[str] = set(emotion_schema.get("emotions", []))
        self.transforms: Dict[str, List[str]] = emotion_schema.get("transforms", {})
        self.allowed_transitions: Dict[str, List[str]] = emotion_schema.get("allowed_transitions", {})
        self.slot_ids: Set[str] = {s["id"] for s in slots.get("slots", [])}
        self.slot_all_tags: Set[str] = set()
        for s in slots.get("slots", []):
            self.slot_all_tags.update(s.get("must", []))
            self.slot_all_tags.update(s.get("forbid", []))
            
        # --- NEW: Load validation rules from config ---
        validation_rules = config.get('validation_rules', {})
        self.vis_set: Set[str] = set(validation_rules.get('lore_visibility', ['public', 'secret']))
    # --- END MODIFICATION ---

    def _ensure(self, cond: bool, msg: str):
        # (Logic Unchanged)
        if not cond:
            raise ValidationError(msg)

    def emotion_ok(self, emo: str):
        # (Logic Unchanged)
        return (emo in self.emotions) or any(emo in alts for alts in self.transforms.values())

    def validate_npc_row(self, row: Dict[str, Any]):
        # (Logic Unchanged)
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
        
        try:
            sem = json.loads(row["style_emotion_map"])
            if not isinstance(sem, dict):
                raise TypeError("not a dict")
        except Exception:
            sem = parse_kv_map_forgiving(row["style_emotion_map"])

        self._ensure(set(sem.keys()).issubset(er | {be}),
                     "style_emotion_map keys must be in emotion_range or baseline_emotion")
        
        at = set(parse_json_list_forgiving(row["allowed_tags"]))
        self._ensure(len(at) > 0, "allowed_tags should not be empty")
        _ = parse_json_list_forgiving(row["taboo_topics"])

    def validate_lore_row(self, row: Dict[str, Any]):
        # (Logic Unchanged)
        required = ["fact_id","entity","fact","tags","visibility"]
        for k in required:
            self._ensure(row.get(k) not in (None, ""), f"lore.{row.get('fact_id')} missing field: {k}")
            
        # --- MODIFIED: Use self.vis_set from config ---
        self._ensure(row["visibility"] in self.vis_set, f"lore.{row['fact_id']} visibility must be in {self.vis_set}")
        # --- END MODIFICATION ---
        _ = parse_json_list_forgiving(row["tags"])

    def validate_slots(self, slots: Dict[str, Any]):
        # (Logic Unchanged)
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
        # (Logic Unchanged)
        lore_tags: Set[str] = set()
        for r in lore:
            lore_tags.update(parse_json_list_forgiving(r["tags"]))
        for r in npcs:
            at = set(parse_json_list_forgiving(r["allowed_tags"]))
            self._ensure(at.issubset(lore_tags), f"npc.{r['npc_id']} allowed_tags contain unknown tags: {at - lore_tags}")