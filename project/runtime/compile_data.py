
from __future__ import annotations
import csv, json, sys
from pathlib import Path
from typing import Dict, Any, List, DefaultDict
from collections import defaultdict
import yaml
from validators import Validators, ValidationError, parse_json_list_forgiving

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CACHE_DIR = Path(__file__).resolve().parent / ".cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

def read_csv(path: Path):
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)

def main() -> int:
    npc_rows = read_csv(DATA / "npc.csv")
    lore_rows = read_csv(DATA / "lore.csv")
    red_rows = read_csv(DATA / "redteam.csv")
    longterm_rows = read_csv(DATA / "memory_longterm.csv")

    with (DATA / "emotion_schema.yaml").open("r", encoding="utf-8") as f:
        emotion_schema = yaml.safe_load(f)
    with (DATA / "slots.yaml").open("r", encoding="utf-8") as f:
        slots = yaml.safe_load(f)

    v = Validators(emotion_schema, slots)
    for r in npc_rows: v.validate_npc_row(r)
    for r in lore_rows: v.validate_lore_row(r)
    v.validate_slots(slots)
    v.cross_validate(npc_rows, lore_rows)

    evidence_index: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in lore_rows:
        for t in parse_json_list_forgiving(r["tags"]):
            evidence_index[t].append({
                "fact_id": r["fact_id"],
                "entity": r["entity"],
                "fact": r["fact"],
                "visibility": r["visibility"],
            })

    allowed_entities = set()
    for npc in npc_rows:
        for t in parse_json_list_forgiving(npc["allowed_tags"]):
            for item in evidence_index.get(t, []):
                allowed_entities.add(item["entity"])
    allowed_entities = sorted(allowed_entities)

    baseline_by_npc = {r["npc_id"]: r["baseline_emotion"] for r in npc_rows}
    tone_guidelines = {s["id"]: s.get("tone_guidelines", {}) for s in slots.get("slots", [])}

    cache = {
        "evidence_index": evidence_index,
        "allowed_entities": allowed_entities,
        "baseline_emotion": baseline_by_npc,
        "tone_guidelines": tone_guidelines,
        "emotion_schema": emotion_schema,
        "npc_count": len(npc_rows),
        "lore_count": len(lore_rows),
        "slots_count": len(slots.get("slots", [])),
    }

    (CACHE_DIR / "compiled.json").write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

    print("[compile] NPCs:", cache["npc_count"])
    print("[compile] Lore facts:", cache["lore_count"])
    print("[compile] Slots:", cache["slots_count"])
    print("[compile] Allowed entities:", len(allowed_entities))
    print("[compile] Evidence tags:", len(evidence_index))
    print("[ok] cache ->", (CACHE_DIR / "compiled.json").as_posix())
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except ValidationError as e:
        print("[validation-error]", e)
        sys.exit(2)
