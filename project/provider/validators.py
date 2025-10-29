# ...existing code...
# -*- coding: utf-8 -*-
"""
简单的写回合规校验器（validators），用于在将事实写入长期公开记忆前做门控判断。

模块说明（中文详细化）：
- 目的：在将自动抽取或生成的“事实”写入长期公开记忆（long-term public memory）之前，
  通过一组可插拔、可配置的策略检查（禁忌话题、机密信息、未授权实体等），
  将明显违规或高风险的候选项拦截掉，避免泄露敏感信息或引入未授权世界设定。
- 依赖/配置：
  - 可选的策略文件：memory_policy.yaml（与本文件同目录），支持以下键：
      - taboo_topics: 列表，包含应视为“禁忌/不公开”的话题关键词（字符串匹配，大小写不敏感）。
      - secrets: 列表，包含触发“机密”拦截的关键词（避免模型“承认/披露”机密）。
      - allowed_entities: 列表，允许在公开记忆中出现的实体/专有名词（其它首字母大写词将被视作“未知实体”）。
    如果未提供该文件，模块会退回到空白策略（即不拦截任何项），便于测试/本地运行。
- 注意事项与局限：
  - 本实现使用非常保守且简单的启发式检测（子串匹配、首字母大写检测等），
    旨在提供一个可工作的骨架。生产环境应替换为更健壮的实现（例如 NER + allowlist/denylist、上下文语义检测、策略服务）。
  - 本模块不会对“事实”做模糊匹配或语义消歧，复杂场景可能导致假阳性或假阴性。
  - 对策略的更新建议通过集中式配置管理（如安全策略仓库）下发，而非在代码中硬编码。
"""

import os
import yaml
from typing import Dict, Any

def _load_policy() -> Dict[str, Any]:
    """
    尝试加载同目录下的 memory_policy.yaml 文件（如果存在），解析为字典。

    返回：
      - dict：解析出的策略字典，若文件不存在或解析失败则返回空 dict。

    约定的 YAML 结构示例：
    taboo_topics:
      - politics
      - explicit_violence
    secrets:
      - master_plan
      - confidential_protocol
    allowed_entities:
      - Elira
      - TownInn
    """
    path = os.path.join(os.path.dirname(__file__), "memory_policy.yaml")
    if not os.path.exists(path):
        # 若找不到配置文件，返回空配置，调用方应注意这意味着“不拦截任何内容”
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            # safe_load 避免执行任意构造器，若文件为空则返回 {}
            return yaml.safe_load(f) or {}
    except Exception:
        # 如解析失败（格式错误等），退回空配置以避免抛出异常中断上层流程
        return {}

# 在模块加载时读取一次配置，便于后续函数使用。
_POLICY = _load_policy()

# 从策略中提取三类名单（若不存在则为空集合）
TABOO_TOPICS = set(_POLICY.get("taboo_topics", []))
SECRETS = set(_POLICY.get("secrets", []))
ALLOWED_ENTITIES = set(_POLICY.get("allowed_entities", []))

def is_taboo(text: str) -> bool:
    """
    检查文本是否命中禁忌话题（taboo）。

    实现细节：
      - 使用小写子串匹配：若任一 taboo topic 在文本中作为子串出现，则判定为命中。
      - 该方法对多语言或同义词不敏感，适用于简单的关键词过滤场景。

    返回：
      - True：文本包含任一禁忌关键词（应被拦截）
      - False：未命中禁忌关键词
    """
    t = (text or "").lower()
    return any(topic.lower() in t for topic in TABOO_TOPICS)

def is_secret(text: str) -> bool:
    """
    检查文本是否涉及“机密”触发项（secret）。

    实现细节：
      - 同样采用小写子串匹配，若文本包含配置的任一 secret 关键词则判定为命中。
      - 用途通常是避免模型在公开记忆中“承认”或“披露”某些内部/保密信息。

    返回：
      - True：包含机密触发项（应被拦截）
      - False：未包含
    """
    t = (text or "").lower()
    return any(s.lower() in t for s in SECRETS)

def mentions_unknown_entity(text: str) -> bool:
    """
    朴素检测文本是否提及未授权/未知的实体（proper noun）。

    方法说明（启发式）：
      - 将文本按空白分词，并剥离常见标点。
      - 若某个词以大写字母开头（首字母大写，且不是句首小写形式），则视为可能的专有名词候选。
      - 若该词不在 ALLOWED_ENTITIES（大小写不敏感匹配）中，则视为“未知实体”，返回 True。
      - 该实现有明显局限：对中文/非拉丁文字、句首大写惯例或缩写/首字母缩写识别不佳，建议在生产中替换为 NER + allowlist 策略。

    返回：
      - True：检测到未授权的实体（建议拦截）
      - False：无明显未知实体
    """
    if not text:
        return False
    # 去除常见标点并分词
    words = [w.strip(".,!?;:\"'()[]{}") for w in text.split()]
    # 预先构建大小写不敏感的允许实体集合，避免在循环中重复构建
    allowed_lower = {e.lower() for e in ALLOWED_ENTITIES}
    for w in words:
        if not w:
            continue
        # 仅对以字母开头的词检查首字母是否大写（主要针对英语/拉丁语场景）
        first_char = w[0]
        if first_char.isalpha() and first_char.isupper():
            # 若该词在允许名单中（忽略大小写）则视为已授权实体
            if w.lower() not in allowed_lower:
                return True
    return False

def passes_all_checks(fact: Dict[str, Any]) -> bool:
    """
    组合检查：在写回长期记忆前调用，确认候选事实是否满足所有策略约束。

    预期 fact 结构（最小）：
      - fact['fact'] : 文本内容（字符串）
      - 其它可选键：'emotion', 'slot' 等（函数主要关注 'fact' 字段）

    检查流程（防御式）：
      1. 若命中 is_taboo -> 拒绝（返回 False）
      2. 若命中 is_secret -> 拒绝
      3. 若命中 mentions_unknown_entity -> 拒绝
      4. 否则通过（返回 True）

    设计理念：
      - 采用“拦截优先”的保守策略：任一子策略不通过即拒绝写回，降低误写入敏感信息的风险。
      - 如果需要更精细的决策（例如记录拒绝原因、阈值化、人工复核队列），可以将本函数改为返回结构化结果（bool + reason）。
    """
    text = fact.get("fact", "") if isinstance(fact, dict) else ""
    if is_taboo(text):
        return False
    if is_secret(text):
        return False
    if mentions_unknown_entity(text):
        return False
    return True
# ...existing code...