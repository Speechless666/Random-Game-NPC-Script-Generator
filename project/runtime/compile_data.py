# ==========================================================
# compile_data.py (runtime/.cache version)
# ==========================================================
# 功能：
#   - 从 ../data/ 目录加载 npc.csv、lore.csv、slots.yaml、emotion_schema.yaml
#   - 在当前目录（即 runtime/）下生成 .cache/compiled.json
#   - 仅做“编译打包”，不含任何 demo 数据或自测代码
# ==========================================================

import os, json, csv, yaml
from pathlib import Path

# ---------- 路径配置 ----------
RUNTIME_DIR = Path(__file__).parent
DATA_DIR = RUNTIME_DIR.parent / "data"
CACHE_DIR = RUNTIME_DIR / ".cache"
CACHE_FILE = CACHE_DIR / "compiled.json"

NPC_CSV = DATA_DIR / "npc.csv"
LORE_CSV = DATA_DIR / "lore.csv"
SLOTS_YAML = DATA_DIR / "slots.yaml"
EMOTION_YAML = DATA_DIR / "emotion_schema.yaml"

# ---------- 工具 ----------
def _safe_yaml(p: Path):
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def _safe_csv_rows(p: Path):
    if not p.exists():
        return []
    with p.open("r", encoding="utf-8") as f:
        return list(csv.DictReader(f))

# ---------- 编译 ----------
def compile_all():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    npc_rows = _safe_csv_rows(NPC_CSV)
    lore_rows = _safe_csv_rows(LORE_CSV)
    slot_rules = _safe_yaml(SLOTS_YAML)
    emotion_schema = _safe_yaml(EMOTION_YAML)

    # 构建 allowed_entities（从 lore.entities/tags 聚合）
    allowed_entities = sorted(list({
        (row.get("entity") or "").strip().lower()
        for row in lore_rows
        if (row.get("entity") or "").strip()
    }))

    # 仅保留 public 可见的 lore
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
    return cache

# ---------- 入口 ----------
def main():
    cache = compile_all()
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    print(f"[ok] cache -> {CACHE_FILE.resolve()}")

if __name__ == "__main__":
    main()
