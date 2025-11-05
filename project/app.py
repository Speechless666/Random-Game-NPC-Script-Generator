# app.py
"""
项目的主 Web 服务器 (HTTP 接口)。
它负责：
1. 在启动时，加载所有模型和组件 (与 test.py 类似)。
2. 提供一个 API 端点 (e.g., /npc_reply) 来接收 Demo 的请求。
3. 调用 controller.run_once 来处理请求。
4. 将结果以 JSON 格式返回给 Demo。
"""

import sys
from pathlib import Path
from typing import Dict, Any

# --- 1. 设置 sys.path (与 test.py 相同) ---
# 确保所有 provider/ 和 runtime/ 模块都能被找到
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# --- 2. 导入 FastAPI 和项目核心组件 ---
try:
    import uvicorn
    from fastapi import FastAPI
except ImportError:
    print("错误: 缺少 FastAPI 或 Uvicorn。")
    print("请运行: pip install fastapi uvicorn[standard]")
    sys.exit(1)

try:
    from runtime.controller import run_once, load_compiled
    from provider.qwen import QwenProvider
    from provider.generator import Generator
    from provider.oocChecker import OOCChecker
    from provider.memory_store import MemoryStore
    from provider.memory_summarizer import MemorySummarizer
except ImportError as e:
    print(f"项目内部导入失败: {e}")
    print("请确保 __init__.py 文件存在于 provider/ 和 runtime/ 目录中。")
    sys.exit(1)

# --- 3. FastAPI 应用实例 ---
app = FastAPI(
    title="NPC AI Project API",
    description="连接 Pygame Demo 和 AI Controller 的 HTTP 接口"
)

# --- 4. 全局状态 (用于保存已初始化的组件) ---
# 这是一个字典，用于在服务器启动时保存所有昂贵的组件
# 这样我们就不必在每次请求时都重新加载它们
CORE_COMPONENTS: Dict[str, Any] = {}


@app.on_event("startup")
def load_core_components():
    """
    服务器启动时执行一次：加载所有模型、数据和组件。
    这与 test.py 中的 _initialize_providers 逻辑相同。
    """
    print("服务器启动中... 正在加载核心组件...")
    
    try:
        # 1. 加载编译数据
        compiled_data = load_compiled()
        CORE_COMPONENTS["compiled_data"] = compiled_data
        print(f"✅ 'compiled.json' (含 {len(compiled_data.get('npc',[]))} NPCs) 加载成功。")

        # 2. 初始化 Provider (假设 QwenProvider 不需要 API key)
        # 注意：如果您的 QwenProvider 依赖环境变量，请确保在此处设置
        provider = QwenProvider()
        CORE_COMPONENTS["provider"] = provider
        print("✅ Provider (QwenProvider) 初始化成功。")

        # 3. 初始化 Generator 和 OOCChecker
        generator = Generator(provider)
        CORE_COMPONENTS["generator"] = generator
        ooc_checker = OOCChecker(provider)
        CORE_COMPONENTS["ooc_checker"] = ooc_checker
        print("✅ Generator 和 OOCChecker 初始化成功。")

        # 4. 初始化记忆模块 (修复：路径在 'project/' 内部)
        memory_store = MemoryStore(longterm_path="project/data/memory_longterm.csv")
        CORE_COMPONENTS["memory_store"] = memory_store
        
        memory_summarizer = MemorySummarizer(provider, ooc_checker)
        CORE_COMPONENTS["memory_summarizer"] = memory_summarizer
        print("✅ MemoryStore 和 MemorySummarizer 初始化成功。")
        
        print("\n🎉 所有核心组件加载完毕。服务器准备就绪。\n")
        
    except Exception as e:
        print(f"❌ CRITICAL: 服务器启动失败，加载组件时出错: {e}")
        # 在真实应用中，这里应该让服务器启动失败
        # raise e


@app.get("/npc_reply")
def get_npc_reply_endpoint(
    npc_id: str, 
    player: str, 
    player_id: str = "P001_Demo" # Demo 暂未提供 player_id，我们用一个固定的
):
    """
    这是 Demo (main.py) 将要调用的主 API 端点。
    它与 main.py 中的 API_URL 匹配。
    """
    
    # 1. 从全局状态中获取已初始化的组件
    generator = CORE_COMPONENTS.get("generator")
    ooc_checker = CORE_COMPONENTS.get("ooc_checker")
    compiled_data = CORE_COMPONENTS.get("compiled_data")
    memory_store = CORE_COMPONENTS.get("memory_store")
    memory_summarizer = CORE_COMPONENTS.get("memory_summarizer")
    
    if not all([generator, ooc_checker, compiled_data, memory_store, memory_summarizer]):
        return {"text": "(错误: 服务器核心组件未正确加载)", "emotion": "sad"}

    print(f"收到请求: NPC={npc_id}, Player={player}")

    # 2. 调用我们的核心逻辑
    try:
        result = run_once(
            user_text=player,
            npc_id=npc_id,
            player_id=player_id,
            generator=generator,
            ooc_checker=ooc_checker,
            compiled_data=compiled_data,
            memory_store=memory_store,
            memory_summarizer=memory_summarizer,
            last_emotion=None # (简单起见，暂不管理会话状态)
        )
        
        # 3. 返回 Demo (main.py) 期望的格式
        # main.py 期望一个 "text" 字段
        return {
            "text": result.get("final_text"),
            "emotion": result.get("final_emotion"),
            "slot": result.get("slot")
        }

    except Exception as e:
        print(f"❌ Controller.run_once 执行时出错: {e}")
        return {"text": f"(Controller 错误: {e})", "emotion": "sad"}


if __name__ == "__main__":
    """
    允许你通过 'python project/app.py' 来直接运行这个服务器。
    """
    print("正在启动 Uvicorn 服务器，监听 http://127.0.0.1:8000")
    # 注意：app="app:app" 意味着 "运行 app.py 文件中的 app 变量"
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)