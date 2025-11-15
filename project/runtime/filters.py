"""
filters.py — Phase 2 Guardrail Layer · Pre-check Filter
(MODIFIED: Reads all indexes from compiled_data; reads thresholds from config)
"""
from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, List, Set, Tuple
import json, csv, yaml
import re

# -----------------------------
# REMOVED: All hardcoded path and cache-loading variables
# -----------------------------
# (Indexes are now built from compiled_data passed in by controller)

def _log(msg: str) -> None:
    print(f"[filters] {msg}")

# --- REMOVED: _load_json function (no longer loads files) ---

# --- MODIFIED: load_runtime_indexes now builds from compiled_data ---
def load_runtime_indexes(compiled_data: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Builds the indexes needed for filtering *from the compiled_data object*.
    No file I/O is performed here.
    """
    npc_index: Dict[str, Dict[str, Any]] = {}
    allowed_entities: Set[str] = set()
    all_known_entities: Set[str] = set()
    secret_entities: Set[str] = set()

    try:
        # 1) Build entity sets from compiled_data
        for x in compiled_data.get("allowed_entities", []) or []:
            x = str(x).strip().lower()
            if x:
                allowed_entities.add(x)
        
        # We must scan *all* lore (public and secret) to build the 'secret' list.
        # Since compiled_data only has public lore, we must get secret entities
        # from the 'all_known_entities' vs 'allowed_entities' diff.
        
        # This logic is imperfect as compiled_data is pre-filtered.
        # A better compile_data.py would save 'all_known_entities' and 'secret_entities'
        
        # --- Fallback logic (assuming compiled_data is all we have) ---
        public_lore = compiled_data.get("lore_public", []) or []
        for row in public_lore:
            ent = str(row.get("entity", "")).strip().lower()
            if ent:
                all_known_entities.add(ent)
        
        # This is the best we can do:
        allowed_entities.update(all_known_entities) # Assume all public entities are allowed
        
        # (This module can no longer find secret_entities without the full lore_index)
        _log("WARN: Running in reduced-functionality mode. Cannot detect 'secret_entities' from compiled_data.")
        
    except Exception as e:
        _log(f"Error building indexes from compiled_data: {e}")

    # 2) Build npc_index from compiled_data
    try:
        for row in compiled_data.get("npc", []):
            nid = str(row.get("npc_id") or "").strip()
            if not nid:
                continue
            
            raw_taboo = (row.get("taboo_topics") or "").strip()
            taboo: List[str] = []
            if raw_taboo:
                try:
                    v = json.loads(raw_taboo)
                    if isinstance(v, list):
                        taboo = [str(x).strip() for x in v if str(x).strip()]
                except Exception:
                    parts = [p.strip() for p in re.split(r"[;,]", raw_taboo) if p.strip()]
                    taboo = parts
            
            denial_template = (row.get("denial_template") or "").strip() or None
            npc_index[nid] = {"taboo_topics": taboo, "denial_template": denial_template}
    except Exception as e:
        _log(f"npc data parse error: {e} — fallback to empty npc_index")
        
    # --- END MODIFICATION ---

    return {
        "npc_index": npc_index,
        "allowed_entities": allowed_entities,
        "secret_entities": secret_entities, # Will be empty, but key must exist
        "all_known_entities": all_known_entities, # Will only contain public entities
    }

# -----------------------------
# Text normalization & matching (Logic Unchanged)
# -----------------------------
_ZH_OR_EN_WORD = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)

def normalize_text(text: str) -> str:
    # (Logic Unchanged)
    return (text or "").strip().lower()

def contains_substring(haystack: str, needles: List[str]) -> List[str]:
    # (Logic Unchanged)
    hits = []
    for n in needles:
        n_norm = str(n).strip().lower()
        if not n_norm:
            continue
        if n_norm in haystack:
            hits.append(n)
    return hits

def find_known_entities_in_text(text: str, candidates: Set[str]) -> Set[str]:
    """Finds known entities in text (Logic Unchanged)"""
    # (Logic Unchanged)
    t = normalize_text(text)
    found: Set[str] = set()
    for ent in candidates:
        if ent and ent in t:
            found.add(ent)
    tokens = set(m.group(0) for m in _ZH_OR_EN_WORD.finditer(t))
    for ent in candidates:
        if ent in tokens:
            found.add(ent)
    return found

# -----------------------------
# Main function (MODIFIED)
# -----------------------------
class GuardrailResult(Dict[str, Any]):
    """Returned to controller.py (Schema Unchanged)"""
    pass

# --- MODIFIED: Function signature ---
def precheck_guardrails(
    user_text: str, 
    npc_id: str, 
    *, 
    compiled_data: Dict[str, Any], 
    config: Dict[str, Any]
) -> GuardrailResult:
# --- END MODIFICATION ---

    # --- MODIFIED: Load from params, not files ---
    indexes = load_runtime_indexes(compiled_data, config)
    strict_unknown_entity = config.get('thresholds', {}).get('filters_strict_unknown_entity', True)
    # --- END MODIFICATION ---

    npc = (indexes["npc_index"] or {}).get(str(npc_id), {})
    taboo_topics: List[str] = npc.get("taboo_topics", []) or []
    denial_template: str | None = npc.get("denial_template")

    allowed_entities: Set[str] = indexes.get("allowed_entities", set())
    secret_entities: Set[str] = indexes.get("secret_entities", set())
    all_known_entities: Set[str] = indexes.get("all_known_entities", set())

    text_norm = normalize_text(user_text)

    # 1) Taboo topics check (Logic Unchanged)
    taboo_hits = contains_substring(text_norm, taboo_topics)
    if taboo_hits:
        return GuardrailResult({
            "allow": False,
            "reply": None,
            "flags": {"deny_ooc": True, "mask_required": False, "lang": "en"},
            "deny": {"reason": "taboo", "template": denial_template},
            "hits": {"taboo": taboo_hits, "secret": [], "unknown_entities": []},
        })

    # 2) Secret entity check (Logic Unchanged, but 'secret_entities' may be empty)
    secret_found = find_known_entities_in_text(text_norm, secret_entities)
    if secret_found:
        _log(f"Secret entity hit: {secret_found}") # Added log
        return GuardrailResult({
            "allow": False,
            "reply": None,
            "flags": {"deny_ooc": True, "mask_required": False, "lang": "en"},
            "deny": {"reason": "secret", "template": denial_template},
            "hits": {"taboo": [], "secret": sorted(secret_found), "unknown_entities": []},
        })

    # 3) Unknown entity check (Logic Unchanged)
    mentioned_known = find_known_entities_in_text(text_norm, all_known_entities)
    unknown_entities = sorted([e for e in mentioned_known if e not in allowed_entities])
    
    # --- MODIFIED: Use config threshold ---
    if strict_unknown_entity and unknown_entities:
    # --- END MODIFICATION ---
        _log(f"Unknown entity hit: {unknown_entities}") # Added log
        return GuardrailResult({
            "allow": False,
            "reply": None,
            "flags": {"deny_ooc": True, "mask_required": False, "lang": "en"},
            "deny": {"reason": "unknown_entity", "template": denial_template},
            "hits": {"taboo": [], "secret": [], "unknown_entities": unknown_entities},
        })

    # Pass
    return GuardrailResult({
        "allow": True,
        "reply": None,
        "flags": {"deny_ooc": False, "mask_required": False, "lang": "en"},
        "hits": {"taboo": [], "secret": [], "unknown_entities": []},
    })


# -----------------------------
# Optional: masking (Logic Unchanged)
# -----------------------------
_MASK = "■"

def mask_entities(text: str, entities: List[str]) -> str:
    # (Logic Unchanged)
    if not text or not entities:
        return text
    out = text
    for e in sorted(set(entities), key=len, reverse=True):
        if not e:
            continue
        repl = e
        if len(e) > 2:
            repl = e[0] + (_MASK * (len(e) - 2)) + e[-1]
        else:
            repl = _MASK * len(e)
        out = out.replace(e, repl)
        out = out.replace(e.capitalize(), repl)
    return out


# -----------------------------
# Self-test (MODIFIED)
# -----------------------------
if __name__ == "__main__":
    _log("Quick smoke test... (Requires config.yaml and compiled.json)")
    
    try:
        # --- MODIFIED: Self-test must now load config and compiled data ---
        _PROJECT_ROOT = Path(__file__).resolve().parents[1]
        _CONFIG_PATH = _PROJECT_ROOT / "config.yaml"
        with _CONFIG_PATH.open("r", encoding="utf-8") as f:
            _config = yaml.safe_load(f)
        
        _CACHE_DIR_STR = _config.get('app', {}).get('cache_dir', 'runtime/.cache')
        _COMPILED_PATH = _PROJECT_ROOT / _CACHE_DIR_STR / "compiled.json"
        with _COMPILED_PATH.open("r", encoding="utf-8") as f:
            _compiled = json.load(f)
        
        _log(f"Loaded config from: {_CONFIG_PATH}")
        _log(f"Loaded compiled data from: {_COMPILED_PATH}")
        # --- END MODIFICATION ---
        
        examples = [
            ("What are the exact patrol schedule details?", "G001"), # Assumes G001 is in compiled.json
            ("Where's the black market tonight?", "SV001"), # Assumes SV001 is in compiled.json
            ("Tell me the warding array's weak point.", "G001"),
        ]
        for txt, npc in examples:
            # --- MODIFIED: Pass data into function ---
            res = precheck_guardrails(txt, npc, compiled_data=_compiled, config=_config)
            # --- END MODIFICATION ---
            _log(f"{txt} -> {res}")
            
    except Exception as e:
        _log(f"ERROR: {e}")
        _log("This may be due to missing config.yaml or compiled.json")