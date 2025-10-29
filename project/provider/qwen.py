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
    def __init__(self, api_key: str):
        # 若没有配置环境变量，请用百炼API Key将下行替换为：api_key="sk-xxx"
        if os.getenv(api_key):
            print("api from env")
            self.client = OpenAI(api_key=os.getenv(api_key),
                                 base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
        # 新加坡节点地址
        else:
            print("api not from env")
            self.client = OpenAI(api_key=api_key, base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1")

    def generate(self, prompt: str, schema=None, max_new_tokens=64, retries=2):
        for attempt in range(retries):
            try:
                print("\nQwenProvider.generate attempt", attempt + 1)
                text = "" # 用于存储生成的文本
                response = self.client.chat.completions.create(
                    model="qwen-plus-2025-04-28",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                    max_tokens=max_new_tokens,
                    extra_body={"enable_thinking": False} # 使用Qwen3开源版模型时，若未启用流式输出，请将这行取消注释，否则会报错
                )
                print("Response received, processing chunks...")
                for chunk in response:
                    # 如果chunk.choices为空，打印usage信息以调试
                    if not chunk.choices:
                        print("\nUsage:")
                        print(chunk.usage)
                    else:
                        delta = chunk.choices[0].delta
                        # 逐步打印生成内容
                        print(delta.content, end='', flush=True)
                        text += delta.content
                #text = response.choices[0].message.content.strip()

                # 强制JSON输出
                if schema:
                    try:
                        parsed = json.loads(text)
                        for key in schema:
                            if key not in parsed:
                                raise ValueError(f"Missing key: {key}")
                        return parsed
                    except Exception:
                        prompt += "\n⚠️ Output must be valid JSON, reformat it and retry."
                        continue
                return {"text": text}

            except Exception as e:
                time.sleep(0.5)
                if attempt == retries - 1:
                    raise APIError(f"Qwen API failed after {retries} retries: \n{str(e)}")

    def judge(self, context: str, output: str):
        """简单OOC风险评估"""
        prompt = f"""
        Judge if the NPC reply stays in character.
        Context: {context}
        NPC reply: {output}
        Output JSON: {{"ooc_risk": float(0~1), "reasons": [..]}}
        """
        return self.generate(prompt, schema=["ooc_risk", "reasons"])
