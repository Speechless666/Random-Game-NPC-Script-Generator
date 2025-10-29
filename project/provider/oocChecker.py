import json

class OOCChecker:
    def __init__(self, provider):
        self.provider = provider

    def judge_ooc(self, ctx, output_json):
        """
        调用 provider 评估模型输出是否 OOC（Out-of-Character）
        """
        try:
            res = self.provider.judge(ctx, json.dumps(output_json))
        except Exception as e:
            print(f"[OOCChecker] Provider judge() 调用失败: {e}")
            res = None

        # === 安全防护 ===
        if not isinstance(res, dict):
            print("[WARN] provider.judge() 返回 None 或非法格式，使用默认值。")
            res = {"ooc_risk": 0.0, "reasons": []}

        ooc_risk = float(res.get("ooc_risk", 0.0))
        reasons = res.get("reasons", [])

        # === 情绪冲突检测与降级 ===
        if ooc_risk > 0.5:
            print(f"⚠️ High OOC risk ({ooc_risk:.2f}): {reasons}")
            output_json["emotion"] = "neutral"
            output_json["meta"] = output_json.get("meta", {})
            output_json["meta"]["ooc_flag"] = True
            output_json["meta"]["ooc_reason"] = reasons
        else:
            output_json["meta"] = output_json.get("meta", {})
            output_json["meta"]["ooc_flag"] = False

        return output_json
