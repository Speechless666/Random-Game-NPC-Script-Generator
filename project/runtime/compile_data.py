# ==========================================================
# compile_data.py (runtime/.cache version)
# ==========================================================
# 功能：
#   - 从 ../data/ 目录加载 npc.csv、lore.csv、slots.yaml、emotion_schema.yaml
#   - 在当前目录（即 runtime/）下生成 .cache/compiled.json
# ==========================================================

import os, json, csv, yaml
from pathlib import Path

# ---------- 路径配置 ----------
RUNTIME_DIR = Path(__file__).parent
DATA_DIR = RUNTIME_DIR.parent / "data"
CACHE_DIR = RUNTIME_DIR / ".cache"
CACHE_FILE = CACHE_DIR / "compiled.json"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ---------- 工具函数 ----------
def _norm(s: str) -> str:
    return (s or "").strip().lower()

def _load_yaml(p: Path):
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def _load_csv_rows(p: Path):
    with open(p, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def _json_or_list(cell: str):
    s = (cell or "").strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return [x.strip() for x in s.split(";") if x.strip()]

# ---------- 构建运行时情绪视图 ----------
def build_emotion_schema_runtime(emotion_schema: dict, slots_doc: dict) -> dict:
    labels = list(
        emotion_schema.get("labels")
        or emotion_schema.get("emotions")
        or ["cheerful", "friendly", "neutral", "serious", "cautious", "annoyed", "sad"]
    )

    triggers = emotion_schema.get("triggers") or {
        "thanks": {"keywords": ["thanks", "thank you", "appreciate"], "votes": {"cheerful": 1.0, "friendly": 0.5}},
        "help": {"keywords": ["help", "assist", "please"], "votes": {"friendly": 0.7, "cautious": 0.3}},
    }

    content = emotion_schema.get("content") or {
        "busy": {"phrases": ["busy", "overwhelmed", "tight schedule"], "votes": {"annoyed": 1.0, "serious": 0.7}},
        "free": {"phrases": ["free today", "taking it easy", "off-duty"], "votes": {"cheerful": 1.0, "friendly": 0.7}},
    }

    tone_map = emotion_schema.get("tone_map") or {
        "serious": {"serious": 0.6, "neutral": 0.4},
        "friendly": {"friendly": 0.6, "cheerful": 0.4},
        "formal": {"serious": 0.5, "neutral": 0.5},
        "casual": {"friendly": 0.5, "cheerful": 0.5},
    }

    return {
        "version": str(emotion_schema.get("version", "unknown")),
        "labels": labels,
        "triggers": triggers,
        "content": content,
        "tone_map": tone_map,
    }

# ---------- 主编译逻辑 ----------
def compile_all() -> dict:
    # 1. 加载文件
    emotion_schema = _load_yaml(DATA_DIR / "emotion_schema.yaml")
    slots_doc = _load_yaml(DATA_DIR / "slots.yaml")
    npc_rows = _load_csv_rows(DATA_DIR / "npc.csv")
    lore_rows = _load_csv_rows(DATA_DIR / "lore.csv")

    # 2. NPC 聚合
    baseline_emotion = {}
    emotion_range_map = {}
    style_emotion_map = {}
    allowed_tags_map = {}
    taboo_topics_map = {}

    for row in npc_rows:
        npc_id = (row.get("npc_id") or row.get("id") or row.get("name") or "").strip()
        if not npc_id:
            continue

        baseline_emotion[npc_id] = _norm(row.get("baseline_emotion") or "neutral")
        er = _json_or_list(row.get("emotion_range") or "")
        emotion_range_map[npc_id] = er or ["neutral", "serious", "friendly", "cheerful"]

        try:
            sem = row.get("style_emotion_map") or "{}"
            style_emotion_map[npc_id] = json.loads(sem) if isinstance(sem, str) else sem
        except Exception:
            style_emotion_map[npc_id] = {"neutral": {"tone": "plain", "prefix": [], "suffix": ["."]}}

        allowed_tags_map[npc_id] = _json_or_list(row.get("allowed_tags") or "") or []
        taboo_topics_map[npc_id] = _json_or_list(row.get("taboo_topics") or "") or []

    # 3. 汇总白名单
    allowed_entities = sorted({ _norm(tag) for tags in allowed_tags_map.values() for tag in (tags or []) })

    # 4. 槽位 tone_guidelines
    tone_guidelines = {}
    for slot_id, cfg in (slots_doc.get("slots") or {}).items():
        tones = cfg.get("tone_guidelines") or []
        if isinstance(tones, str):
            tones = [tones]
        tone_guidelines[slot_id] = [ _norm(t) for t in tones ]
    
    slot_rules = {}
    for slot_id, cfg in (slots_doc.get("slots") or {}).items(): 
        tones = cfg.get("tone_guidelines") or []
        if isinstance(tones, str):
            tones = [tones]
        must = cfg.get("must") or []
        forbid = cfg.get("forbid") or []
        if isinstance(must, str):   must = [must]
        if isinstance(forbid, str): forbid = [forbid]
        slot_rules[slot_id] = {
            "tone_guidelines": [ _norm(t) for t in tones ],
            "must":            [ _norm(x) for x in must ],
            "forbid":          [ _norm(x) for x in forbid ],
        }

    # 5. 构建运行时情绪 schema
    emo_rt = build_emotion_schema_runtime(emotion_schema, slots_doc)

    # 6. 提取 public lore
    public_lore = [r for r in lore_rows if _norm(r.get("visibility")) == "public"]

    # 7. 汇总缓存
    cache = {
        "emotion_schema": emotion_schema,
        "emotion_schema_runtime": emo_rt,
        "tone_guidelines": tone_guidelines,
        "baseline_emotion": baseline_emotion,
        "emotion_range_map": emotion_range_map,
        "style_emotion_map": style_emotion_map,
        "allowed_entities": allowed_entities,
        "lore_public": public_lore,
        "slot_rules": slot_rules,
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
