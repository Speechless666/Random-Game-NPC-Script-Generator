# provider/oocChecker.py
import json

class OOCChecker:
    # --- MODIFIED: __init__ now accepts config ---
    def __init__(self, provider, config: dict):
        self.provider = provider
        # Load the threshold from config, fallback to 0.5 if not found
        thresholds_config = config.get('thresholds', {})
        self.ooc_risk_threshold = thresholds_config.get('ooc_high', 0.5)
        print(f"[OOCChecker] Initialized. OOC risk threshold set to: {self.ooc_risk_threshold}")
    # --- END MODIFICATION ---

    def judge_ooc(self, ctx, output_json):
        """
        Calls the provider to evaluate if the model output is OOC (Out-of-Character)
        """
        try:
            res = self.provider.judge(ctx, json.dumps(output_json))
        except Exception as e:
            print(f"[OOCChecker] Provider judge() call failed: {e}")
            res = None

        # === Safety Guard (Logic Unchanged) ===
        if not isinstance(res, dict):
            print("[WARN] provider.judge() returned None or invalid format. Using defaults.")
            res = {"ooc_risk": 0.0, "reasons": []}

        ooc_risk = float(res.get("ooc_risk", 0.0))
        reasons = res.get("reasons", [])

        # === Emotion Conflict Detection & Fallback (MODIFIED) ===
        # --- MODIFIED: Use the threshold from config ---
        if ooc_risk > self.ooc_risk_threshold:
        # --- END MODIFICATION ---
            print(f"⚠️ High OOC risk ({ooc_risk:.2f}): {reasons}")
            output_json["emotion"] = "neutral"
            output_json["meta"] = output_json.get("meta", {})
            output_json["meta"]["ooc_flag"] = True
            output_json["meta"]["ooc_reason"] = reasons
        else:
            output_json["meta"] = output_json.get("meta", {})
            output_json["meta"]["ooc_flag"] = False

        return output_json