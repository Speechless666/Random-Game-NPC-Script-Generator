# -*- coding: utf-8 -*-
"""
runtime/qrouter_v2.py
自适应玩家输入预处理/路由（零依赖版）
- 动态从 data 构建词表；不用预设同义词字典
- 槽位路由：TF-IDF 余弦，相似度最高者为候选；低置信回落 small_talk
- 实体/标签解析：对 allowed_entities + lore.entities/tags 做相似度匹配
- PRF 伪相关反馈：从最相近的 lore 文档中自动提取若干“查询锚点（must seeds）”
- 输出统一接口供 filters/retriever/controller 使用
"""

from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, List, Tuple, Iterable
import json, yaml, re, math

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_FILE   = PROJECT_ROOT / "runtime" / ".cache" / "compiled.json"
SLOTS_FILE   = PROJECT_ROOT / "data" / "slots.yaml"

# --------------------------
# Basic text utils (no dict)
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
    t = re.sub(r"[^\w\s]", " ", t)      # 去标点
    t = re.sub(r"\s+", " ", t).strip()  # 压空白
    return t

def _tok(s: str) -> List[str]:
    t = _canon(s)
    toks = t.split()
    # 若疑似中文/无空格文本：退化为 2-gram
    if len(toks) <= 1 and len(t) > 4:
        return [t[i:i+2] for i in range(len(t)-1)]
    return toks

def _filter_tokens(toks: Iterable[str]) -> List[str]:
    out = []
    for w in toks:
        if len(w) <= 1:  # 去除极短
            continue
        if w in _STOP:
            continue
        # 极简词干（不依赖外部库）
        for suf in ("ing","ed","es","s"):
            if len(w) > len(suf)+2 and w.endswith(suf):
                w = w[:-len(suf)]
                break
        out.append(w)
    return out

# --------------------------
# TF-IDF (manual)
# --------------------------
def _build_tfidf(docs: List[List[str]]) -> Tuple[List[Dict[str,float]], Dict[str,float]]:
    """输入：每个文档的token列表；输出：每个文档的tfidf向量(稀疏dict)和 idf表"""
    N = len(docs)
    df: Dict[str,int] = {}
    for toks in docs:
        for term in set(toks):
            df[term] = df.get(term, 0) + 1
    idf = {t: math.log((N+1)/(c+0.5)) + 1.0 for t, c in df.items()}  # S-IDF 平滑
    vecs: List[Dict[str,float]] = []
    for toks in docs:
        tf: Dict[str,int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        # l2 正则化
        v: Dict[str,float] = {}
        for t, f in tf.items():
            v[t] = (1.0 + math.log(f)) * idf.get(t, 0.0)
        norm = math.sqrt(sum(x*x for x in v.values())) or 1.0
        for t in list(v.keys()):
            v[t] /= norm
        vecs.append(v)
    return vecs, idf

def _vec(text: str, idf: Dict[str,float]) -> Dict[str,float]:
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
    if len(a) > len(b): a, b = b, a
    s = 0.0
    for t, wa in a.items():
        wb = b.get(t)
        if wb: s += wa*wb
    return s

# --------------------------
# Load data
# --------------------------
def _load_compiled() -> Dict[str,Any]:
    data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    return {
        "allowed_entities": data.get("allowed_entities", []) or [],
        "lore_public": data.get("lore_public", []) or [],
    }

def _load_slots() -> Dict[str,Any]:
    return yaml.safe_load(SLOTS_FILE.read_text(encoding="utf-8")) or {}

# --------------------------
# Build corpora (dynamic)
# --------------------------
def _build_slot_corpus(slots: Dict[str,Any]) -> Tuple[List[str], List[str]]:
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
# Public API
# --------------------------
def prepare(user_text: str) -> Dict[str,Any]:
    """
    Return:
    {
      text_norm: str,
      slot: str,
      route_confidence: float,
      must: list[str],          # 若 slot 无 must，则用 PRF 从 lore 里自动选1~2个锚点
      forbid: list[str],        # 来自 slots.yaml（若有）
      tags: list[str],          # 基于相似度对齐到的 tags（前若干个）
      resolved_entities: list[str],  # 基于相似度对齐到的实体（前若干个）
      prf_terms: list[str],     # PRF 提取的高权重词
      notes: {slot_rank: [...], entity_matches: [...], tag_matches: [...], prf_sources: [fact_ids...] }
    }
    """
    user_text = user_text or ""
    text_norm = _canon(user_text)

    compiled = _load_compiled()
    slots    = _load_slots()

    # --- 1) SLOT ROUTING (TF-IDF on slot docs) ---
    slot_names, slot_docs = _build_slot_corpus(slots)
    slot_docs_tok = [_filter_tokens(_tok(d)) for d in slot_docs]
    slot_vecs, slot_idf = _build_tfidf(slot_docs_tok)
    qv = _vec(user_text, slot_idf)
    sims = [(slot_names[i], _cos(qv, slot_vecs[i])) for i in range(len(slot_names))]
    sims.sort(key=lambda x: x[1], reverse=True)
    best_slot, best_score = sims[0]
    second = sims[1][1] if len(sims) > 1 else 0.0
    # 置信度：top 与次优的 margin（0..1）
    margin = max(0.0, best_score - second)
    route_conf = max(best_score, margin)
    # 低置信度回退
    if route_conf < 0.15:
        best_slot, route_conf = "small_talk", 0.35

    slot_def = (slots.get("slots") or {}).get(best_slot, {}) or {}
    base_must   = [ _canon(x) for x in (slot_def.get("must") or []) if str(x).strip() ]
    base_forbid = [ _canon(x) for x in (slot_def.get("forbid") or []) if str(x).strip() ]

    # --- 2) ENTITY/TAG RESOLUTION (TF-IDF similarity over candidate list) ---
    ents, tags = _build_entity_tag_corpus(compiled)

    # 将每个候选作为一条“文档”，与 query 计算相似度
    def _rank_list(cands: List[str], topk=6):
        docs = [" ".join([c, c.replace("_"," ")]) for c in cands]  # 加入变体提升鲁棒性
        docs_tok = [_filter_tokens(_tok(d)) for d in docs]
        vecs, idf = _build_tfidf(docs_tok) if docs_tok else ({}, {})
        q = _vec(user_text, idf) if docs_tok else {}
        scores = []
        for i, c in enumerate(cands):
            s = _cos(q, vecs[i]) if q else 0.0
            if s > 0.0:
                scores.append((c, s))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:topk]

    ent_rank = _rank_list(ents, topk=6)
    tag_rank = _rank_list(tags, topk=6)

    resolved_entities = [c for c,_ in ent_rank[:5]]
    resolved_tags     = [c for c,_ in tag_rank[:5]]

    # --- 3) PRF: 从最相近 lore 文档自动抽“查询锚点” ---
    lore_texts, lore_rows = _build_lore_docs(compiled)
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
        # 汇总 top-k 文档里的高权重词
        acc: Dict[str, float] = {}
        for i in topk:
            for t, w in lvecs[i].items():
                if t in _STOP or len(t) <= 2: 
                    continue
                acc[t] = acc.get(t, 0.0) + w
        prf_terms = [t for t,_ in sorted(acc.items(), key=lambda x: x[1], reverse=True)[:6]]

    # --- 4) 组装 must/tags ---
    must_final: List[str] = list(base_must)
    if best_slot == "small_talk" or route_conf < 0.35:
        pass  # 保持 must_final 为空
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
# Self-test
# --------------------------
if __name__ == "__main__":
    print("[qrouter_v2] self-test…")
    try:
        for txt in [
            "what's new in the market?",
            "any news from the marketplace guild?",
            "tell me about patrol shifts near the east gate",
            "hi there, how's your day?",
        ]:
            r = prepare(txt)
            import pprint; print("\n---", txt, "---"); pprint.pp(r, width=110, compact=False)
    except Exception as e:
        print("[qrouter_v2] ERROR:", e)
