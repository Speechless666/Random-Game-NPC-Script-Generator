import json
# runtime/ooc_checker.py
class OOCChecker:
    def __init__(self, provider):
        self.provider = provider

    # OOC评估接口
    def judge_ooc(self, ctx, output_json):
        res = self.provider.judge(ctx, json.dumps(output_json))
        # 简单的情绪冲突检测
        if res["ooc_risk"] > 0.5:
            print("⚠️ High OOC risk:", res["reasons"])
            output_json["emotion"] = "neutral"  # 降级情绪
        return output_json
