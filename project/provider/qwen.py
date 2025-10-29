# provider/qwen.py
# ref: https://bailian.console.aliyun.com/?tab=model#/model-market/detail/qwen3-vl-32b-thinking
import json, time, random, os
from openai import OpenAI
try:
    # prefer absolute import when package root is available
    from project.provider.base import BaseProvider, APIError
except Exception:
    # fallback to relative/ local import for simpler execution contexts
    try:
        from . import BaseProvider, APIError
    except Exception:
        from base import BaseProvider, APIError  # type: ignore

class QwenProvider(BaseProvider):
    def __init__(self, apikey: str):
        # 若没有配置环境变量，请用百炼API Key将下行替换为：api_key="sk-xxx"
        if os.getenv(apikey):
            print("api from env")
            self.client = OpenAI(api_key=os.getenv(apikey),
                                 base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
        # 中国/新加坡节点地址
        else:
            print("api not from env")
            self.client = OpenAI(api_key=apikey, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")

    def generate(self, prompt: str, schema=None, retries=2):
        # retries 用于强制 JSON 输出时的重试次数
        for attempt in range(retries):
            try:
                print("\nQwenProvider.generate attempt", attempt + 1)
                text = "" # 用于存储生成的文本
                response = self.client.chat.completions.create(
                    model="qwen-plus-2025-04-28",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.8,
                    extra_body={"enable_thinking": False} # 使用Qwen3开源版模型时，若未启用流式输出，请将这行取消注释，否则会报错
                )
                text = response.choices[0].message.content.strip()
                #print(text)
                # 强制JSON输出
                if schema:
                    try:
                        parsed = json.loads(text)
                        print("Parsed type:", type(parsed))
                        for key in schema:
                            if key not in parsed:
                                raise ValueError(f"Missing key: {key}")
                        print("Parsed JSON:", parsed)
                        return parsed
                    except Exception as e:
                        print("[ERROR]", e)
                        print("[WARN] Failed to parse JSON output, retrying...")
                        prompt += "\n⚠️ Output must be valid JSON, reformat it and retry."
                        continue
                return {"text": text}

            except Exception as e:
                time.sleep(0.5)
                if attempt == retries - 1:
                    raise APIError(f"Qwen API failed after {retries} retries: \n{str(e)}")
        print("Exiting generate after retries.")
        return text

    def judge(self, context: str, output: str):
        """简单OOC风险评估"""
        prompt = f"""
        Judge if the NPC reply stays in character.
        Context: {context}
        NPC reply: {output}
        Output JSON: {{"ooc_risk": float(0~1), "reasons": [..]}}
        """
        return self.generate(prompt, schema=["ooc_risk", "reasons"], retries=1)
