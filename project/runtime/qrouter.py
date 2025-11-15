# -*- coding: utf-8 -*-
"""
runtime/qrouter_v2.py
Adaptive player input preprocessing/routing (zero-dependency version)
- Dynamically builds vocab from data; no preset synonym dicts
- Slot routing: TF-IDF cosine, highest similarity is candidate; low confidence falls back to small_talk
- Entity/Tag parsing: Similarity matching against allowed_entities + lore.entities/tags
- PRF: Auto-extracts "must seeds" from the most similar lore documents
- Outputs a uniform interface for filters/retriever/controller
"""

from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, List, Tuple, Iterable
import json, yaml, re, math

# --- REMOVED: Hardcoded path globals (PROJECT_ROOT, CACHE_FILE, SLOTS_FILE) ---
# Data will be passed into the 'prepare' function

# --------------------------
# Basic text utils (Logic Unchanged)
# --------------------------
_STOP = set("""
a an the and or but if while of in on at by for to from with without into onto over under as is are was were be been being
this that these those here there it its they them he she we you i me my your his her our their
how what when where who which whose why whether
do does did done doing have has had having get got getting make makes made making
not no nor only just also too very much more most less least
can could may might must shall should will would
s am re ve ll d
""".split())

def _canon(s: str) -> str:
    t = (s or "").lower()
    t = re.sub(r"[^\w\s]", " ", t)      # Remove punctuation
    t = re.sub(r"\s+", " ", t).strip()  # Compress whitespace
    return t

def _tok(s: str) -> List[str]:
    # (Logic Unchanged)
    t = _canon(s)
    toks = t.split()
    if len(toks) <= 1 and len(t) > 4:
        return [t[i:i+2] for i in range(len(t)-1)]
    return toks

def _filter_tokens(toks: Iterable[str]) -> List[str]:
    # (Logic Unchanged)
    out = []
    for w in toks:
        if len(w) <= 1:
            continue
        if w in _STOP:
            continue
        for suf in ("ing","ed","es","s"):
            if len(w) > len(suf)+2 and w.endswith(suf):
                w = w[:-len(suf)]
                break
        out.append(w)
    return out

# --------------------------
# TF-IDF (manual) (Logic Unchanged)
# --------------------------
def _build_tfidf(docs: List[List[str]]) -> Tuple[List[Dict[str,float]], Dict[str,float]]:
    # (Logic Unchanged)
    N = len(docs)
    df: Dict[str,int] = {}
    for toks in docs:
        for term in set(toks):
            df[term] = df.get(term, 0) + 1
    idf = {t: math.log((N+1)/(c+0.5)) + 1.0 for t, c in df.items()}
    vecs: List[Dict[str,float]] = []
    for toks in docs:
        tf: Dict[str,int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        v: Dict[str,float] = {}
        for t, f in tf.items():
            v[t] = (1.0 + math.log(f)) * idf.get(t, 0.0)
        norm = math.sqrt(sum(x*x for x in v.values())) or 1.0
        for t in list(v.keys()):
            v[t] /= norm
        vecs.append(v)
    return vecs, idf

def _vec(text: str, idf: Dict[str,float]) -> Dict[str,float]:
    # (Logic Unchanged)
    toks = _filter_tokens(_tok(text))
    tf: Dict[str,int] = {}
    for t in toks: tf[t] = tf.get(t, 0) + 1
    v: Dict[str,float] = {}
    for t, f in tf.items():
        w = (1.0 + math.log(f)) * idf.get(t, 0.0)
        if w != 0.0: v[t] = w
    norm = math.sqrt(sum(x*x for x in v.values())) or 1.0
    for t in list(v.keys()):
        v[t] /= norm
    return v

def _cos(a: Dict[str,float], b: Dict[str,float]) -> float:
    # (Logic Unchanged)
    if len(a) > len(b): a, b = b, a
    s = 0.0
    for t, wa in a.items():
        wb = b.get(t)
        if wb: s += wa*wb
    return s

# --------------------------
# Load data (REMOVED)
# --------------------------
# --- REMOVED _load_compiled() and _load_slots() ---
# (Data will be passed into 'prepare')

# --------------------------
# Build corpora (Logic Unchanged)
# (These now take the data as parameters)
# --------------------------
def _build_slot_corpus(slots: Dict[str,Any]) -> Tuple[List[str], List[str]]:
    # (Logic Unchanged)
    names, docs = [], []
    for slot_name, spec in (slots.get("slots") or {}).items():
        desc = " ".join([
            slot_name.replace("_"," "),
            " ".join(spec.get("must", []) or []),
            " ".join(spec.get("tone_guidelines", []) or []),
            (spec.get("description") or "")
        ]).strip()
        names.append(slot_name)
        docs.append(desc or slot_name)
    if not names:
        names, docs = ["small_talk"], ["small talk casual chatter"]
    return names, docs

def _build_entity_tag_corpus(compiled: Dict[str,Any]) -> Tuple[List[str], List[str]]:
    # (Logic Unchanged)
    ents = list(dict.fromkeys([str(x) for x in compiled["allowed_entities"]]))
    lore_ents, lore_tags = [], []
    for r in compiled["lore_public"]:
        e = str(r.get("entity","")).strip()
        if e: lore_ents.append(e)
        tags = r.get("tags", [])
        if isinstance(tags, list):
            lore_tags.extend([str(t) for t in tags])
        elif isinstance(tags, str) and tags.strip():
            lore_tags.extend([t.strip() for t in re.split(r"[;,]", tags) if t.strip()])
    ents = list(dict.fromkeys(ents + lore_ents))
    tags = list(dict.fromkeys(lore_tags))
    return ents, tags

def _build_lore_docs(compiled: Dict[str,Any]) -> Tuple[List[str], List[Dict[str,Any]]]:
    # (Logic Unchanged)
    texts, rows = [], []
    for r in compiled["lore_public"]:
        txt = " ".join([
            str(r.get("fact","")),
            str(r.get("entity","")),
            " ".join(r.get("tags", [])) if isinstance(r.get("tags"), list)
                else str(r.get("tags","")).replace(";",",")
        ])
        texts.append(txt)
        rows.append(r)
    return texts, rows

# --------------------------
# Phrase extraction utilities (Logic Unchanged)
# --------------------------
def _extract_phrases(text: str, min_length=2, max_length=3) -> List[str]:
    # (Logic Unchanged)
    tokens = _filter_tokens(_tok(text))
    phrases = []
    for n in range(min_length, max_length + 1):
        for i in range(len(tokens) - n + 1):
            phrase = " ".join(tokens[i:i+n])
            phrases.append(phrase)
    return phrases

def _phrase_similarity(user_text: str, phrases: List[str]) -> Dict[str, float]:
    # (Logic Unchanged)
    user_norm = _canon(user_text)
    scores = {}
    for phrase in phrases:
        if phrase in user_norm:
            scores[phrase] = 2.0
            scores[phrase] += len(phrase.split()) * 0.1
    return scores

# --------------------------
# Enhanced entity recognition (Logic Unchanged)
# --------------------------
def _enhanced_rank_list(cands: List[str], user_text: str, topk=6):
    # (Logic Unchanged)
    docs = []
    for c in cands:
        variants = [
            c,
            c.replace("_", " "),
            c.replace("_", ""),
            " ".join(c.split("_")),
        ]
        docs.append(" ".join(variants))
    
    docs_tok = [_filter_tokens(_tok(d)) for d in docs]
    vecs, idf = _build_tfidf(docs_tok) if docs_tok else ({}, {})
    q = _vec(user_text, idf) if docs_tok else {}
    scores = []
    for i, c in enumerate(cands):
        s = _cos(q, vecs[i]) if q else 0.0
        user_norm = _canon(user_text)
        if c in user_norm:
            s += 0.5
        if s > 0.0:
            scores.append((c, s))
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[:topk]

# --------------------------
# Public API (MODIFIED)
# --------------------------
def prepare(user_text: str, compiled_data: Dict[str, Any], config: Dict[str, Any]) -> Dict[str,Any]:
    """
    (MODIFIED: Now accepts compiled_data and config)
    Return:
    {
      text_norm: str,
      slot: str,
      route_confidence: float,
      must: list[str],
      forbid: list[str],
      tags: list[str],
      resolved_entities: list[str],
      prf_terms: list[str],
      notes: { ... }
    }
    """
    user_text = user_text or ""
    text_norm = _canon(user_text)

    # --- MODIFIED: Load data from parameters, not files ---
    # compiled = _load_compiled()  <-- REMOVED
    slot_rules = compiled_data.get('slot_rules', {})
    # --- END MODIFICATION ---

    # --- MODIFIED: Load thresholds from config ---
    thresholds_config = config.get('thresholds', {})
    fallback_threshold = thresholds_config.get('qrouter_fallback_threshold', 0.15)
    fallback_new_conf = thresholds_config.get('qrouter_fallback_new_conf', 0.35)
    prf_score_threshold = thresholds_config.get('qrouter_prf_score_threshold', 0.3)
    prf_phrase_weight = thresholds_config.get('qrouter_prf_phrase_weight', 0.7)
    must_decision_threshold = thresholds_config.get('qrouter_must_decision_threshold', 0.35)
    # --- END MODIFICATION ---

    # --- 1) SLOT ROUTING (TF-IDF on slot docs) ---
    slot_names, slot_docs = _build_slot_corpus(slot_rules) # <-- MODIFIED
    slot_docs_tok = [_filter_tokens(_tok(d)) for d in slot_docs]
    slot_vecs, slot_idf = _build_tfidf(slot_docs_tok)
    qv = _vec(user_text, slot_idf)
    sims = [(slot_names[i], _cos(qv, slot_vecs[i])) for i in range(len(slot_names))]
    sims.sort(key=lambda x: x[1], reverse=True)
    best_slot, best_score = sims[0]
    second = sims[1][1] if len(sims) > 1 else 0.0
    margin = max(0.0, best_score - second)
    route_conf = max(best_score, margin)
    
    # Low confidence fallback
    # --- MODIFIED: Use config threshold ---
    if route_conf < fallback_threshold:
        best_slot, route_conf = "small_talk", fallback_new_conf
    # --- END MODIFICATION ---

    slot_def = (slot_rules.get("slots") or {}).get(best_slot, {}) or {} # <-- MODIFIED
    base_must   = [ _canon(x) for x in (slot_def.get("must") or []) if str(x).strip() ]
    base_forbid = [ _canon(x) for x in (slot_def.get("forbid") or []) if str(x).strip() ]

    # --- 2) ENTITY/TAG RESOLUTION (TF-IDF similarity over candidate list) ---
    ents, tags = _build_entity_tag_corpus(compiled_data) # <-- MODIFIED

    ent_rank = _enhanced_rank_list(ents, user_text, topk=6)
    tag_rank = _enhanced_rank_list(tags, user_text, topk=6)

    resolved_entities = [c for c,_ in ent_rank[:5]]
    resolved_tags     = [c for c,_ in tag_rank[:5]]

    # --- 3) PRF: Auto-extract "must seeds" from most similar lore docs ---
    lore_texts, lore_rows = _build_lore_docs(compiled_data) # <-- MODIFIED
    prf_terms: List[str] = []
    prf_sources: List[str] = []
    
    if lore_texts:
        ltoks = [_filter_tokens(_tok(t)) for t in lore_texts]
        lvecs, lidf = _build_tfidf(ltoks)
        ql = _vec(user_text, lidf)
        lsims = [(i, _cos(ql, lvecs[i])) for i in range(len(lvecs))]
        lsims.sort(key=lambda x: x[1], reverse=True)
        topk = [i for i, s in lsims[:5] if s > 0.0]
        prf_sources = [str(lore_rows[i].get("fact_id") or i) for i in topk]
        
        acc: Dict[str, float] = {}
        for i in topk:
            for t, w in lvecs[i].items():
                if t in _STOP or len(t) <= 2: 
                    continue
                acc[t] = acc.get(t, 0.0) + w
            
            # --- MODIFIED: Use config threshold ---
            if best_score < prf_score_threshold:
            # --- END MODIFICATION ---
                phrases = _extract_phrases(lore_texts[i])
                phrase_scores = _phrase_similarity(user_text, phrases)
                for phrase, score in phrase_scores.items():
                    acc[phrase] = acc.get(phrase, 0.0) + score
        
        prf_candidates = []
        for term, score in acc.items():
            if ' ' in term:
                # --- MODIFIED: Use config weight ---
                adjusted_score = score * prf_phrase_weight
                # --- END MODIFICATION ---
            else:
                adjusted_score = score
            prf_candidates.append((term, adjusted_score))
        
        prf_candidates.sort(key=lambda x: x[1], reverse=True)
        prf_terms = [term for term, _ in prf_candidates[:6]]

    # --- 4) Assemble must/tags ---
    must_final: List[str] = list(base_must)
    # --- MODIFIED: Use config threshold ---
    if best_slot == "small_talk" or route_conf < must_decision_threshold:
    # --- END MODIFICATION ---
        pass
    else:
        if not must_final:
            if resolved_entities:
                must_final.append(_canon(resolved_entities[0]))
            elif resolved_tags:
                must_final.append(_canon(resolved_tags[0]))
            elif prf_terms:
                must_final.append(prf_terms[0])

    out = {
        "text_norm": text_norm,
        "slot": best_slot,
        "route_confidence": round(float(route_conf), 3),
        "must": must_final,
        "forbid": base_forbid,
        "tags": resolved_tags,
        "resolved_entities": resolved_entities,
        "prf_terms": prf_terms,
        "notes": {
            "slot_rank": [(n, round(float(s), 3)) for n, s in sims[:5]],
            "entity_matches": [(c, round(float(s),3)) for c, s in ent_rank],
            "tag_matches": [(c, round(float(s),3)) for c, s in tag_rank],
            "prf_sources": prf_sources,
        }
    }
    return out

# --------------------------
# Self-test (MODIFIED)
# --------------------------
if __name__ == "__main__":
    print("[qrouter_v2] self-test…")
    print("WARNING: This test now requires a valid 'compiled.json' and 'config.yaml'")
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
        
        print(f"Loaded config from: {_CONFIG_PATH}")
        print(f"Loaded compiled data from: {_COMPILED_PATH}")
        # --- END MODIFICATION ---

        for txt in [
            "what's new in the market?",
            "any news from the marketplace guild?",
            "tell me about patrol shifts near the east gate",
            "hi there, how's your day?",
        ]:
            # --- MODIFIED: Pass data into prepare ---
            r = prepare(txt, compiled_data=_compiled, config=_config)
            # --- END MODIFICATION ---
            import pprint; print("\n---", txt, "---"); pprint.pp(r, width=110, compact=False)
    except Exception as e:
        print("[qrouter_v2] ERROR:", e)
        print("This may be due to missing config.yaml or compiled.json")