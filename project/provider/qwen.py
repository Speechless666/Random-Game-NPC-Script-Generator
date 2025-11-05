# provider/qwen.py
# ref: https://bailian.console.aliyun.com/?tab=model#/model-market/detail/qwen3-vl-32b-thinking
import json, time, random, os
from openai import OpenAI  # 保留，不动你原来的导入
try:
    # prefer absolute import when package root is available
    from provider.base import BaseProvider, APIError
except Exception:
    # fallback to relative/ local import for simpler execution contexts
    try:
        from .base import BaseProvider, APIError
    except Exception:
        from base import BaseProvider, APIError  # type: ignore


class QwenProvider(BaseProvider):
    def __init__(self, apikey=os.getenv("QWEN_API_KEY")):
        # 保持原来的 apikey 参数名和环境变量名
        try:
            self._model_name = "qwen-plus"
            # 若没有配置环境变量，请用百炼API Key将下行替换为：api_key="sk-xxx"
            if os.getenv(apikey):
                print("api from env")
                self.client = OpenAI(api_key=os.getenv(apikey),
                                    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
            # 中国/新加坡节点地址
            else:
                print("api not from env")
                self.client = OpenAI(api_key=apikey, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
        except Exception as e:
            raise APIError(f"Failed to initialize QwenProvider: {str(e)}")

    def generate(self, prompt: str, schema=None, retries=2):
        # retries 用于强制 JSON 输出时的重试次数
        last_error = None
        
        for attempt in range(retries):
            try:
                print(f"\nQwenProvider.generate attempt {attempt + 1}")

                # 如果需要JSON输出，增强提示
                actual_prompt = prompt
                if schema:
                    # 明确要求JSON格式
                    schema_desc = ", ".join([f'"{key}": ...' for key in schema])
                    actual_prompt = f"""{prompt}

IMPORTANT: You MUST return valid JSON format with these exact keys: {schema_desc}
Return ONLY the JSON object, no other text or explanations.
Example format: {json.dumps({key: "example_value" for key in schema}, ensure_ascii=False)}
"""

                resp = self.client.chat.completions.create(
                    model=self._model_name,
                    messages=[
                        {"role": "user", "content": actual_prompt}
                    ],
                    temperature=0.8)
                text = resp.choices[0].message.content.strip()

                if not text:
                    try:
                        text = "".join(
                            p.text for c in getattr(resp, "candidates", []) 
                            for p in getattr(c, "content", {}).get("parts", [])
                            if hasattr(p, "text")
                        ).strip()
                    except Exception:
                        text = ""
                        raise ValueError("No text found in response candidates")

                print(f"Raw response: {text}")  # 调试信息

                # 清理可能的Markdown代码块
                cleaned_text = text.strip()
                if cleaned_text.startswith("```json"):
                    cleaned_text = cleaned_text[7:]
                if cleaned_text.startswith("```"):
                    cleaned_text = cleaned_text[3:]
                if cleaned_text.endswith("```"):
                    cleaned_text = cleaned_text[:-3]
                cleaned_text = cleaned_text.strip()

                # 强制JSON输出
                if schema:
                    try:
                        parsed = json.loads(cleaned_text)
                        
                        # 修复：正确处理列表和字典的验证
                        if isinstance(parsed, list):
                            # 如果是列表，验证每个元素
                            for i, item in enumerate(parsed):
                                if not isinstance(item, dict):
                                    raise ValueError(f"Item {i} is not a dictionary")
                                for key in schema:
                                    if key not in item:
                                        raise ValueError(f"Missing key '{key}' in item {i}: {item}")
                        elif isinstance(parsed, dict):
                            # 如果是字典，验证顶层键
                            for key in schema:
                                if key not in parsed:
                                    raise ValueError(f"Missing key: {key}")
                        else:
                            raise ValueError(f"Expected list or dict, got {type(parsed)}")
                            
                        return parsed
                    except Exception as e:
                        print(f"[ERROR] JSON parse failed: {e}")
                        print(f"[ERROR] Raw text was: {text}")
                        print(f"[ERROR] Cleaned text was: {cleaned_text}")
                        last_error = e
                        
                        # 重试时使用更强的提示
                        if attempt < retries - 1:
                            time.sleep(1)
                            continue
                        else:
                            # 最后一次尝试仍然失败，抛出异常
                            raise

                # 非JSON返回
                return {"text": text}

            except Exception as e:
                print(f"[ERROR] API call failed: {e}")
                last_error = e
                time.sleep(1)

        raise APIError(f"Qwen API failed after {retries} retries: {str(last_error)}")

    def judge(self, context: str, output: str):
        """简单OOC风险评估"""
        prompt = f"""
        Judge if the NPC reply stays in character.
        Context: {context}
        NPC reply: {output}
        Output JSON: {{"ooc_risk": 0.0, "reasons": []}}
        """
        return self.generate(prompt, schema=["ooc_risk", "reasons"], retries=1)