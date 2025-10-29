"""记忆摘要器：从最近对话中抽取候选事实，并对 slot == "past_story" 的个人经历类事实进行合规过滤。

该模块实现 C3 要求的行为要点：
- 当候选事实标注为 slot == "past_story" 时，可允许一定程度的即兴补全，但在写入长期公开记忆之前必须经过合规检查（validators）与越界/情绪风险检查（OOC）。
- 提供的 API：
    - summarize(recent_dialogue, slot=None) -> 返回候选事实列表，每项为 dict，包含键：{"fact":..., "emotion":..., "slot":...}
- 依赖项说明：
    - provider: 需要实现 generate(prompt, schema=...) 方法，用于调用 LLM 进行结构化抽取。
    - ooc_checker（可选）：需要实现 judge_ooc(context, output_json) 方法，返回可能被修改过的 output_json（例如加入 ooc_risk 或调整 emotion）。
    - validators 模块：需实现 passes_all_checks(candidate) 函数，用于政策/白名单/禁忌/机密等合规检查。
- 写回决策：
    - summarize 仅返回已通过初筛的候选事实（最终是否持久化写入由上游调用者决定）。
    - 对于 past_story，若 validators 拒绝或 OOC 风险过高（超过阈值），会被过滤掉，不会纳入返回列表。
"""

from typing import List, Dict, Any, Optional
import os

# 尝试以包的绝对路径导入 validators（当项目作为包运行时更稳定）
try:
    import project.runtime.validators as validators
except Exception:
    # 回退到相对导入或本地 import，便于在不同执行上下文下运行
    try:
        from . import validators
    except Exception:
        import validators  # type: ignore

# OOC 风险阈值：当 ooc_checker 返回的 ooc_risk 大于该值时视为"高风险"并拒绝写回
OOC_RISK_THRESHOLD = 0.5


class MemorySummarizer:
    """记忆摘要器类。

    初始化参数：
      - provider: LLM 提供者对象，需实现 generate(prompt, schema=...)。
      - ooc_checker: 可选的 OOC 检查器实例，需实现 judge_ooc(context, output_json)。

    说明：
      - 本类负责从 recent_dialogue 中抽取 1-3 条候选事实（fact），并在 slot 为 past_story 时对其进行合规与 OOC 风险过滤。
      - 返回的候选仅表示“可写回的候选集”，并不直接写入长期存储；调用方应在写回前再次做最终检查（防止竞态或策略更新）。
    """

    def __init__(self, provider, ooc_checker=None):
        # LLM 提供者（用于结构化抽取）
        self.provider = provider
        # 可选的越界/OOC 检查器
        self.ooc_checker = ooc_checker

    def summarize(self, recent_dialogue: List[str], slot: Optional[str] = None) -> List[Dict[str, Any]]:
        """从最近对话中抽取 1-3 条候选事实。

        行为细节：
          - recent_dialogue: 字符串列表，每项为一轮对话（例如 "NPC: ..." / "Player: ..."）。
          - slot: 当上层已知欲抽取的 slot（例如 'past_story'）时可传入；否则使用 provider 返回的 slot 字段。
          - 对于 slot == 'past_story' 的候选，会走 validators 合规检查；若通过并且有 ooc_checker，则会进一步调用 OOC 检查器判定 ooc_risk。
          - 返回值：候选事实列表，每项为 dict：{"fact": str, "emotion": str, "slot": str}。
        """

        # 将对话列表合并为供 LLM 使用的文本块
        text = "\n".join(recent_dialogue)

        # Prompt：请求 LLM 从对话中提炼 1-3 条“持久事实”
        # 注意：提示文本保持英文以便与 LLM 交互时语义更稳定
        prompt = f"""
        From the following dialogue, extract 1-3 persistent facts about NPC or player relations.
        Output a JSON list; each item must contain: fact, emotion, slot.
        Dialogue: {text}
        """

        try:
            # 请求 provider 返回结构化数据，schema 指定需要的字段
            raw = self.provider.generate(prompt, schema=["fact", "emotion", "slot"])
        except Exception:
            # 当生成失败时，安全策略是返回空列表（避免误写入）
            return []

        # 将 provider 的返回标准化为候选列表（支持 dict 或 list 两种常见格式）
        candidates = []
        if isinstance(raw, list):
            candidates = raw
        elif isinstance(raw, dict):
            # 有些 provider 可能只返回单个对象
            candidates = [raw]

        accepted: List[Dict[str, Any]] = []

        # 遍历每个候选并做校验
        for c in candidates:
            # 规范化字段：去除首尾空白，设置默认情绪为 'neutral'
            fact_text = c.get("fact", "").strip()
            emotion = c.get("emotion", "neutral")
            # 如果 provider 未返回 slot，则使用函数入参提供的 slot（如果有）
            cslot = c.get("slot", slot)

            candidate = {"fact": fact_text, "emotion": emotion, "slot": cslot}

            # 对于 past_story 插槽，允许写回但需额外合规与风险检查
            if cslot == "past_story":
                # 首先运行 validators 的策略检查（例如 taboo/topics/secret/allowlist 等）
                # validators.passes_all_checks 应返回 True 表示通过，否则 False 表示被策略拒绝
                if not validators.passes_all_checks(candidate):
                    # 若任一策略不通过则直接跳过该候选，不纳入 accepted
                    # 这里采用“防守式”策略：失败即拦截，记录/告警由上层处理
                    continue

                # 若提供了 OOC 检查器，则进一步检测情绪越界或内容越界的风险
                if self.ooc_checker is not None:
                    # 复用既有 OOC 接口：judge_ooc(context, output_json)
                    # 该接口可以返回修改后的 output_json（例如调整 emotion）并可包含 'ooc_risk' 字段
                    # 将 recent_dialogue 作为上下文传入
                    res = self.ooc_checker.judge_ooc(recent_dialogue, candidate)

                    # 解析返回：若返回为 dict 则尝试读取 ooc_risk
                    ooc_risk = res.get("ooc_risk", 0) if isinstance(res, dict) else 0

                    # 若 OOC 风险超过阈值，则拒绝该候选写回
                    if ooc_risk and ooc_risk > OOC_RISK_THRESHOLD:
                        continue

                    # 如果 OOC 检查器对情绪做了调整，则采用其返回值（否则保留原 emotion）
                    candidate["emotion"] = res.get("emotion", candidate["emotion"]) if isinstance(res, dict) else candidate["emotion"]

            # 非 past_story（例如 public_fact 等）或通过了全部检查的 past_story，会被加入 accepted 列表
            # 注意：这里 accepted 只是“通过初筛并可被上层写入”的候选，上层仍需在写回前执行最终的审计/记录
            accepted.append(candidate)

        # 返回已通过筛选的候选事实列表；调用者负责持久化写入（例如 MemoryStore.write_longterm）
        return accepted