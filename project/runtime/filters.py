"""
filters.py — 阶段2 护栏层·前置过滤

职能（来自计划书阶段2）：
- 白名单实体检查、禁区命中检测、打码策略；生成前快速护栏，优先 deny_ooc。

依赖（由阶段1编译产物提供，运行时加载 runtime/.cache/*.json）：
- npc_index.json: { npc_id: {"taboo_topics": [str], "denial_template": str, "allowed_tags": [str] } }
- allowed_entities.json: { "entities": [str] }                  # 按 allowed_tags 汇总 lore.entity 去重
- lore_index.json: [ {"fact_id": str, "entity": str, "fact": str, "tags": [str], "visibility": "public|secret"} ]

注：若上述文件不存在，本模块以“空集合”降级，不会报错，但会降低拦截效果。
"""
from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, List, Set, Tuple
import json, csv
import re

# -----------------------------
# 路径与缓存装载
# -----------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]          # project/
CACHE_DIR = PROJECT_ROOT / "runtime" / ".cache"
DATA_DIR = PROJECT_ROOT / "data"

NPC_INDEX_F = CACHE_DIR / "npc_index.json"
ALLOWED_ENTITIES_F = CACHE_DIR / "allowed_entities.json"
LORE_INDEX_F = CACHE_DIR / "lore_index.json"

# 轻量日志接口（可替换为 runtime/logger.py）
# NOTE: All strings are expected to be English in downstream stages. This module only passes flags.
def _log(msg: str) -> None:
    print(f"[filters] {msg}")


def _load_json(path: Path, default):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception as e:
        _log(f"cache load error: {path.name}: {e} — fallback to default")
        return default


def load_runtime_indexes() -> Dict[str, Any]:
    npc_index: Dict[str, Dict[str, Any]] = {}
    allowed_entities: Set[str] = set()
    all_known_entities: Set[str] = set()
    secret_entities: Set[str] = set()

    try:
        compiled = _load_json(CACHE_DIR / "compiled.json", {})
        for x in compiled.get("allowed_entities", []) or []:
            x = str(x).strip().lower()
            if x:
                allowed_entities.add(x)
        for row in compiled.get("lore_public", []) or []:
            ent = str(row.get("entity", "")).strip().lower()
            if ent:
                all_known_entities.add(ent)
    except Exception:
        pass

    # 2) 兼容历史缓存（若存在则并入）
    try:
        allowed_entities_j = _load_json(ALLOWED_ENTITIES_F, {"entities": []})
        for x in allowed_entities_j.get("entities", []) or []:
            x = str(x).strip().lower()
            if x:
                allowed_entities.add(x)
    except Exception:
        pass
    try:
        lore_index: List[Dict[str, Any]] = _load_json(LORE_INDEX_F, [])
        for row in lore_index:
            ent = str(row.get("entity", "")).strip().lower()
            if ent:
                all_known_entities.add(ent)
            if str(row.get("visibility", "")).lower() == "secret" and ent:
                secret_entities.add(ent)
    except Exception:
        pass

    # 3) 直接从 data/npc.csv 构建 npc_index（taboo_topics / denial_template）
    try:
        npc_csv = DATA_DIR / "npc.csv"
        if npc_csv.exists():
            with npc_csv.open("r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    nid = str(row.get("npc_id") or "").strip()
                    if not nid:
                        continue
                    # 解析 taboo_topics：支持 JSON 或 用逗号/分号分隔
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
        _log(f"npc.csv load error: {e} — fallback to empty npc_index")

    # 4) 从 data/lore.csv 抽取 secret 实体（若有）
    try:
        lore_csv = DATA_DIR / "lore.csv"
        if lore_csv.exists():
            with lore_csv.open("r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    vis = str(row.get("visibility", "")).strip().lower()
                    ent = str(row.get("entity", "")).strip().lower()
                    if ent:
                        all_known_entities.add(ent)
                        if vis == "secret":
                            secret_entities.add(ent)
    except Exception as e:
        _log(f"lore.csv load error: {e} — skip secret_entities enrichment")
    return {
        "npc_index": npc_index,
        "allowed_entities": allowed_entities,
        "secret_entities": secret_entities,
        "all_known_entities": all_known_entities,
    }

# -----------------------------
# 文本归一化与匹配工具
# -----------------------------
_ZH_OR_EN_WORD = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)

def normalize_text(text: str) -> str:
    return (text or "").strip().lower()


def contains_substring(haystack: str, needles: List[str]) -> List[str]:
    hits = []
    for n in needles:
        n_norm = str(n).strip().lower()
        if not n_norm:
            continue
        if n_norm in haystack:
            hits.append(n)
    return hits


def find_known_entities_in_text(text: str, candidates: Set[str]) -> Set[str]:
    """最稳妥的做法还是 substring 命中；同时对英文边界做一次粗切分以减少误报。
    兼容中英文：中文直接用子串匹配，英文则同时匹配完整词。
    """
    t = normalize_text(text)
    found: Set[str] = set()
    # 直接子串先扫一遍（中文友好）
    for ent in candidates:
        if ent and ent in t:
            found.add(ent)
    # 英文补一个整词匹配（避免如 "king" 命中 "viking"）
    tokens = set(m.group(0) for m in _ZH_OR_EN_WORD.finditer(t))
    for ent in candidates:
        if ent in tokens:
            found.add(ent)
    return found

# -----------------------------
# 对外主函数
# -----------------------------
class GuardrailResult(Dict[str, Any]):
    """Returned to controller.py
    {
        "allow": bool,
        "reply": Optional[str],            # None here; generator crafts wording in English
        "flags": {"deny_ooc": bool, "mask_required": bool, "lang": "en"},
        "deny": {"reason": str, "template": Optional[str]} | None,
        "hits": {"taboo": [str], "secret": [str], "unknown_entities": [str]},
    }
    """
    pass


def precheck_guardrails(user_text: str, npc_id: str, *, strict_unknown_entity: bool = True) -> GuardrailResult:
    indexes = load_runtime_indexes()
    npc = (indexes["npc_index"] or {}).get(str(npc_id), {})
    taboo_topics: List[str] = npc.get("taboo_topics", []) or []
    denial_template: str | None = npc.get("denial_template")  # Optional; refusal wording will be crafted later by generator

    allowed_entities: Set[str] = indexes.get("allowed_entities", set())
    secret_entities: Set[str] = indexes.get("secret_entities", set())
    all_known_entities: Set[str] = indexes.get("all_known_entities", set())

    text_norm = normalize_text(user_text)

    # 1) 明确禁区词条命中- 角色不愿谈论的名单
    taboo_hits = contains_substring(text_norm, taboo_topics)
    if taboo_hits:
        return GuardrailResult({
            "allow": False,
            "reply": None,  # wording will be generated downstream (English, in-character)
            "flags": {"deny_ooc": True, "mask_required": False, "lang": "en"},
            "deny": {"reason": "taboo", "template": denial_template},
            "hits": {"taboo": taboo_hits, "secret": [], "unknown_entities": []},
        })

    # 2) 命中“secret 实体”（来自 lore.visibility=secret 的实体）
    secret_found = find_known_entities_in_text(text_norm, secret_entities)
    if secret_found:
        return GuardrailResult({
            "allow": False,
            "reply": None,
            "flags": {"deny_ooc": True, "mask_required": False, "lang": "en"},
            "deny": {"reason": "secret", "template": denial_template},
            "hits": {"taboo": [], "secret": sorted(secret_found), "unknown_entities": []},
        })

    # 3) 白名单外的实体（只拦截“我们已知的实体Universe中，但不在allowed里的那些”）- 防止ai根据玩家输入的内容乱编
    mentioned_known = find_known_entities_in_text(text_norm, all_known_entities)
    unknown_entities = sorted([e for e in mentioned_known if e not in allowed_entities])
    if strict_unknown_entity and unknown_entities:
        return GuardrailResult({
            "allow": False,
            "reply": None,
            "flags": {"deny_ooc": True, "mask_required": False, "lang": "en"},
            "deny": {"reason": "unknown_entity", "template": denial_template},
            "hits": {"taboo": [], "secret": [], "unknown_entities": unknown_entities},
        })

    # 通过
    return GuardrailResult({
        "allow": True,
        "reply": None,
        "flags": {"deny_ooc": False, "mask_required": False, "lang": "en"},
        "hits": {"taboo": [], "secret": [], "unknown_entities": []},
    })


# -----------------------------
# Optional: masking (if controller chooses "allow but mask" policy). All outputs remain in English.
# -----------------------------
_MASK = "■"

def mask_entities(text: str, entities: List[str]) -> str:
    if not text or not entities:
        return text
    out = text
    for e in sorted(set(entities), key=len, reverse=True):
        if not e:
            continue
        # 粗暴替换：保持长度，替换为同长度方块符，保留首尾各1字符可读性
        repl = e
        if len(e) > 2:
            repl = e[0] + (_MASK * (len(e) - 2)) + e[-1]
        else:
            repl = _MASK * len(e)
        out = out.replace(e, repl)
        out = out.replace(e.capitalize(), repl)
    return out


# -----------------------------
# 快速自测（可在命令行运行：python -m runtime.filters）
# -----------------------------
if __name__ == "__main__":
    # Quick smoke test; assumes caches exist. Outputs are structured (no fixed wording here).
    examples = [
        ("What are the exact patrol schedule details?", "G001"),
        ("Where's the black market tonight?", "S001"),
        ("Tell me the warding array's weak point.", "G001"),
    ]
    for txt, npc in examples:
        res = precheck_guardrails(txt, npc)
        _log(f"{txt} -> {res}")
