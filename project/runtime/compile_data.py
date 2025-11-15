# ==========================================================
# compile_data.py (Config-driven version)
# ==========================================================
# Function:
#   - Loads config.yaml to find data/ and runtime/.cache/ paths.
#   - Loads npc.csv, lore.csv, slots.yaml, emotion_schema.yaml from config paths.
#   - Generates .cache/compiled.json in the config-specified cache dir.
#   - This only "compiles" data; it contains no demo data.
# ==========================================================

import os, json, csv, yaml
from pathlib import Path

# ---------- REMOVED: All hardcoded path variables ----------
# (Paths will now be read from the config)

# ---------- Utilities (Logic Unchanged) ----------
def _safe_yaml(p: Path):
    if not p.exists():
        print(f"[compile_data] WARN: YAML file not found, returning empty: {p}")
        return {}
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def _safe_csv_rows(p: Path):
    if not p.exists():
        print(f"[compile_data] WARN: CSV file not found, returning empty: {p}")
        return []
    with p.open("r", encoding="utf-8") as f:
        return list(csv.DictReader(f))

# ---------- Compilation (Logic Unchanged, but paths are now parameters) ----------
def compile_all(config: dict, project_root: Path):
    """
    Loads all data files specified in the config and builds the cache object.
    """
    
    # --- MODIFIED: Get paths from config ---
    data_files = config.get('data_files', {})
    app_config = config.get('app', {})
    
    # Construct full paths relative to the 'project/' folder (project_root)
    npc_csv_path = project_root / data_files.get('npc', 'data/npc.csv')
    lore_csv_path = project_root / data_files.get('lore', 'data/lore.csv')
    slots_yaml_path = project_root / data_files.get('slots', 'data/slots.yaml')
    emotion_yaml_path = project_root / data_files.get('emotion_schema', 'data/emotion_schema.yaml')
    
    cache_dir_path = project_root / app_config.get('cache_dir', 'runtime/.cache')
    # --- END MODIFICATION ---

    cache_dir_path.mkdir(parents=True, exist_ok=True)

    npc_rows = _safe_csv_rows(npc_csv_path)
    lore_rows = _safe_csv_rows(lore_csv_path)
    slot_rules = _safe_yaml(slots_yaml_path)
    emotion_schema = _safe_yaml(emotion_yaml_path)

    # --- This logic is identical to your original ---
    # Build allowed_entities (aggregated from lore.entities/tags)
    allowed_entities = sorted(list({
        (row.get("entity") or "").strip().lower()
        for row in lore_rows
        if (row.get("entity") or "").strip()
    }))

    # Keep only publicly visible lore
    public_lore = []
    for row in lore_rows:
        vis = (row.get("visibility") or "public").strip().lower()
        if vis == "public":
            public_lore.append({
                "fact_id": row.get("fact_id"),
                "entity": row.get("entity"),
                "fact": row.get("fact"),
                "tags": row.get("tags"),
                "visibility": vis
            })

    cache = {
        "npc": npc_rows,
        "allowed_entities": allowed_entities,
        "lore_public": public_lore,
        "slot_rules": slot_rules,
        "emotion_schema_runtime": emotion_schema,
    }
    return cache, cache_dir_path

# ---------- Entrypoint ----------
def main():
    
    # --- MODIFIED: Load config first ---
    project_root = Path(__file__).parent.parent # This is 'project/'
    config_path = project_root / "config.yaml"
    
    if not config_path.exists():
        print(f"[compile_data] ERROR: config.yaml not found at: {config_path}")
        return

    print(f"[compile_data] Loading config from: {config_path}")
    with config_path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    # --- END MODIFICATION ---
    
    cache, cache_dir = compile_all(config, project_root)
    
    # --- MODIFIED: Use config-driven cache path ---
    # Note: The filename 'compiled.json' is assumed by controller.py
    cache_file_path = cache_dir / "compiled.json"
    # --- END MODIFICATION ---

    with open(cache_file_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
        
    print(f"[ok] Cache written to -> {cache_file_path.resolve()}")

if __name__ == "__main__":
    main()