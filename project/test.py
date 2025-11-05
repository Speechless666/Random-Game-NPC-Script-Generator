# test_dialogue_system.py
"""
对话系统完整测试 - 基于实际数据
(已重构：本文件只负责初始化和调用 controller)
(已更新：初始化并传入记忆模块)
"""

import json
import sys
from pathlib import Path
from typing import Dict, Any, List
import argparse
import pprint # 用于漂亮地打印字典

# 添加项目路径
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from runtime.controller import run_once, load_compiled
    from provider.qwen import QwenProvider
    from provider.generator import Generator
    from provider.oocChecker import OOCChecker
    # --- 新增：导入记忆模块 ---
    from provider.memory_store import MemoryStore
    from provider.memory_summarizer import MemorySummarizer
    # --- 结束新增 ---
except ImportError as e:
    print(f"导入错误: {e}")
    print("请确保所有依赖模块都已正确实现")
    print(" (如果报告 'validators' 缺失, 请创建 'validators.py' 文件)")
    sys.exit(1)


class DialogueSystemTester:
    """对话系统测试器 - (已重构)"""
    
    def __init__(self, use_real_provider=False):
        self.use_real_provider = use_real_provider
        # --- 修改：初始化记忆模块 ---
        self.memory_store = None # 将在 provider 初始化后创建
        self.memory_summarizer = None # 将在 provider 初始化后创建
        # --- 结束修改 ---
        self.provider = None
        self.generator = None
        self.ooc_checker = None
        self.api_status = {
            "provider_initialized": False,
            "generator_initialized": False,
            "ooc_checker_initialized": False,
            "memory_store_initialized": False, # <-- 新增
            "memory_summarizer_initialized": False # <-- 新增
        }
        
        self.compiled_data = self._load_actual_compiled_data()
        
        if use_real_provider:
            self._initialize_providers()
        else:
            print("🔶 使用模拟模式运行（无真实API调用）")
    
    def _load_actual_compiled_data(self) -> Dict[str, Any]:
        """加载实际的编译数据"""
        try:
            compiled_data = load_compiled()
            print("✅ 成功加载编译数据")
            print(f"  - NPC数量: {len(compiled_data.get('npc', []))}")
            print(f"  - 公开知识数量: {len(compiled_data.get('lore_public', []))}")
            return compiled_data
        except Exception as e:
            print(f"❌ 加载编译数据失败: {e}")
            print("将使用模拟数据运行")
            return {}
    
    def _initialize_providers(self):
        """初始化真实的 provider（如果需要）"""
        try:
            print("🔄 正在初始化真实 provider...")
            self.provider = QwenProvider()
            
            print("🔄 测试API连接...")
            test_result = self._test_api_connection()
            
            if test_result:
                self.api_status["provider_initialized"] = True
                self.generator = Generator(self.provider)
                self.api_status["generator_initialized"] = True
                self.ooc_checker = OOCChecker(self.provider)
                self.api_status["ooc_checker_initialized"] = True
                
                # --- 新增：初始化记忆模块 ---
                # (使用 fixmemory_store.py 的构造函数，它不需要参数)
                self.memory_store = MemoryStore(longterm_path="project/data/memory_longterm.csv") 
                self.api_status["memory_store_initialized"] = True
                
                # (memory_summarizer 依赖 provider 和 ooc_checker)
                self.memory_summarizer = MemorySummarizer(self.provider, self.ooc_checker)
                self.api_status["memory_summarizer_initialized"] = True
                # --- 结束新增 ---
                
                print("✅ 真实 provider 和记忆模块初始化成功")
            else:
                print("❌ API测试失败，回退到模拟模式")
                self.use_real_provider = False
                
        except Exception as e:
            print(f"❌ 真实 provider 初始化失败: {e}")
            print("将使用模拟模式运行")
            self.use_real_provider = False
    
    def _test_api_connection(self) -> bool:
        """测试API连接是否正常"""
        # ... (此函数保持不变) ...
        try:
            # ( ... 此处省略 ... )
            test_prompt = "Please respond with just the word 'success'"
            result = self.provider.generate(test_prompt)
            if result and isinstance(result, dict) and "text" in result:
                if "success" in result["text"].lower():
                    return True
            elif result and isinstance(result, str) and "success" in result.lower():
                return True
            return False
        except Exception as e:
            print(f"❌ API连接测试失败: {e}")
            return False
    
    def print_api_status(self):
        """打印API状态信息"""
        self.print_subsection("API状态")
        status_icons = { True: "✅", False: "❌" }
        
        print(f"使用真实Provider: {status_icons[self.use_real_provider]}")
        if self.use_real_provider:
            print(f"Provider初始化: {status_icons[self.api_status['provider_initialized']]}")
            print(f"Generator初始化: {status_icons[self.api_status['generator_initialized']]}")
            print(f"OOC检查器初始化: {status_icons[self.api_status['ooc_checker_initialized']]}")
            print(f"MemoryStore初始化: {status_icons[self.api_status['memory_store_initialized']]}")
            print(f"MemorySummarizer初始化: {status_icons[self.api_status['memory_summarizer_initialized']]}")
        else:
            print("🔶 当前运行在模拟模式")
    
    def print_section(self, title: str, width=80):
        print("\n" + "=" * width)
        print(f" {title} ".center(width, "="))
        print("=" * width)
    
    def print_subsection(self, title: str):
        print(f"\n--- {title} ---")

    # --- 移除所有 test_phase... 函数 ---

    def run_complete_test(self, user_text: str, npc_id: str = "SV001", player_id: str = "P001"):
        """(已简化) 运行完整的测试流程"""
        print(f"\n🎭 开始对话测试")
        print(f"🗣️  NPC: {npc_id}")
        print(f"👤 玩家: {player_id}")
        print(f"💬 用户输入: '{user_text}'")
        
        self.print_api_status()
        
        if not self.use_real_provider:
            print("🔶 处于模拟模式，跳过 controller 调用。")
            return
            
        if not all([self.generator, self.ooc_checker, self.compiled_data, self.memory_store, self.memory_summarizer]):
            print("❌ 核心组件 (Generator, OOC, Memory, CompiledData) 未完全初始化。")
            return

        try:
            self.print_section("调用 Controller.run_once")
            
            controller_result = run_once(
                user_text=user_text,
                npc_id=npc_id,
                player_id=player_id, # <-- 传入 player_id
                generator=self.generator,
                ooc_checker=self.ooc_checker,
                compiled_data=self.compiled_data,
                memory_store=self.memory_store, # <-- 传入 memory_store
                memory_summarizer=self.memory_summarizer, # <-- 传入 memory_summarizer
                last_emotion=None 
            )
            
            print("✅ Controller.run_once 执行完毕")
            
            self.print_section("测试总结 (Controller 返回的完整结果)")
            pprint.pprint(controller_result)
            
            # --- 新增：记忆监测 ---
            self.print_subsection("记忆监测 (Memory Monitor)")
            short_term_events = self.memory_store.get_short_window()
            print(f"短期记忆中现在的事件 (共 {len(short_term_events)} 条):")
            pprint.pprint(short_term_events)
            
            memory_audit = controller_result.get('audit', {}).get('memory', {})
            if memory_audit.get("facts_written", 0) > 0:
                print(f"✅ 成功写入 {memory_audit['facts_written']} 条长期记忆:")
                pprint.pprint(memory_audit.get("facts", []))
            # --- 结束新增 ---

            print("\n--- 快速预览 ---")
            print(f"👤 NPC: {npc_id}")
            print(f"💬 用户输入: {user_text}")
            print(f"🎯 识别槽位: {controller_result.get('slot')}")
            print(f"🎭 最终情绪: {controller_result.get('final_emotion')}")
            print(f"📝 生成内容: {controller_result.get('final_text')}")
            
        except Exception as e:
            print(f"❌ 测试过程中出现错误: {e}")
            import traceback
            traceback.print_exc()


def main():
    """主函数 - 直接运行预设测试用例"""
    
    test_cases = [
        {"npc_id": "SV001", "user_text": "When is the Luau and where is it held?", "description": "向Shane打招呼"},
        {"npc_id": "SV001", "user_text": "When is the Luau and where is it held?", "description": "询问Shane的工作 (可能触发 past_story)"},
        {"npc_id": "SV002", "user_text": "When is the Luau and where is it held?", "description": "日常聊天"},
    ]
    
    print("🎮 星露谷物语对话系统测试")
    print("=" * 50)
    
    use_real = input("是否使用真实API？(y/N): ").strip().lower() == 'y'
    
    tester = DialogueSystemTester(use_real_provider=use_real)
    
    player_id = "P001_Session" # 设定一个本次测试的玩家ID

    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{'#' * 60}")
        print(f"测试用例 {i}: {test_case['description']}")
        print(f"{'#' * 60}")
        
        # 传入 player_id
        tester.run_complete_test(test_case['user_text'], test_case['npc_id'], player_id=player_id)
        
        if i < len(test_cases):
            input("\n按回车键继续下一个测试...")
    
    print("\n🎉 所有测试用例执行完成！")

if __name__ == "__main__":
    main()