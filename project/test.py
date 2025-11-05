# test_dialogue_system.py
"""
对话系统完整测试 - 基于实际数据
直接运行即可看到完整的对话流程和情绪计算细节
"""

import json
import sys
from pathlib import Path
from typing import Dict, Any, List
import argparse

# 添加项目路径
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from runtime.controller import run_once, load_compiled
    from runtime.qrouter import prepare as route_prepare
    from runtime.retriever import retrieve_public_evidence
    from runtime.emotion_engine import pre_hint, post_infer, realize_style
    from runtime.filters import precheck_guardrails
    from provider.memory_store import MemoryStore
    from provider.memory_summarizer import MemorySummarizer
    from provider.qwen import QwenProvider
    from provider.generator import Generator
    from provider.oocChecker import OOCChecker
except ImportError as e:
    print(f"导入错误: {e}")
    print("请确保所有依赖模块都已正确实现")
    sys.exit(1)


class DialogueSystemTester:
    """对话系统测试器 - 基于实际数据"""
    
    def __init__(self, use_real_provider=False):
        self.use_real_provider = use_real_provider
        self.memory_store = MemoryStore()
        self.provider = None
        self.generator = None
        self.ooc_checker = None
        self.memory_summarizer = None
        self.api_status = {
            "provider_initialized": False,
            "generator_initialized": False,
            "ooc_checker_initialized": False,
            "memory_summarizer_initialized": False,
            "test_calls_made": 0,
            "test_calls_successful": 0
        }
        
        # 加载实际编译数据
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
            print(f"  - 允许实体数量: {len(compiled_data.get('allowed_entities', []))}")
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
            
            # 测试API连接
            print("🔄 测试API连接...")
            test_result = self._test_api_connection()
            
            if test_result:
                self.api_status["provider_initialized"] = True
                self.generator = Generator(self.provider)
                self.api_status["generator_initialized"] = True
                self.ooc_checker = OOCChecker(self.provider)
                self.api_status["ooc_checker_initialized"] = True
                self.memory_summarizer = MemorySummarizer(self.provider, self.ooc_checker)
                self.api_status["memory_summarizer_initialized"] = True
                print("✅ 真实 provider 初始化成功")
            else:
                print("❌ API测试失败，回退到模拟模式")
                self.use_real_provider = False
                
        except Exception as e:
            print(f"❌ 真实 provider 初始化失败: {e}")
            print("将使用模拟模式运行")
            self.use_real_provider = False
    
    def _test_api_connection(self) -> bool:
        """测试API连接是否正常"""
        try:
            self.api_status["test_calls_made"] += 1
            # 简单的测试调用
            test_prompt = "Please respond with just the word 'success'"
            result = self.provider.generate(test_prompt)
            
            if result and isinstance(result, dict) and "text" in result:
                if "success" in result["text"].lower():
                    self.api_status["test_calls_successful"] += 1
                    print("✅ API连接测试成功")
                    return True
            elif result and isinstance(result, str) and "success" in result.lower():
                self.api_status["test_calls_successful"] += 1
                print("✅ API连接测试成功")
                return True
            
            print("❌ API测试返回异常结果")
            return False
            
        except Exception as e:
            print(f"❌ API连接测试失败: {e}")
            return False
    
    def print_api_status(self):
        """打印API状态信息"""
        self.print_subsection("API状态")
        status_icons = {
            True: "✅",
            False: "❌"
        }
        
        print(f"使用真实Provider: {status_icons[self.use_real_provider]}")
        if self.use_real_provider:
            print(f"Provider初始化: {status_icons[self.api_status['provider_initialized']]}")
            print(f"Generator初始化: {status_icons[self.api_status['generator_initialized']]}")
            print(f"OOC检查器初始化: {status_icons[self.api_status['ooc_checker_initialized']]}")
            print(f"记忆总结器初始化: {status_icons[self.api_status['memory_summarizer_initialized']]}")
            print(f"API测试调用: {self.api_status['test_calls_made']}次")
            print(f"API成功调用: {self.api_status['test_calls_successful']}次")
            
            if self.api_status['test_calls_made'] > 0:
                success_rate = (self.api_status['test_calls_successful'] / self.api_status['test_calls_made']) * 100
                print(f"API成功率: {success_rate:.1f}%")
        else:
            print("🔶 当前运行在模拟模式")
    
    def print_section(self, title: str, width=80):
        """打印章节标题"""
        print("\n" + "=" * width)
        print(f" {title} ".center(width, "="))
        print("=" * width)
    
    def print_subsection(self, title: str):
        """打印子章节标题"""
        print(f"\n--- {title} ---")
    
    def get_npc_profile(self, npc_id: str) -> Dict[str, Any]:
        """从编译数据获取NPC配置"""
        npcs = self.compiled_data.get('npc', [])
        for npc in npcs:
            if npc.get('npc_id') == npc_id:
                return npc
        # 默认配置
        return {
            "npc_id": npc_id,
            "baseline_emotion": "neutral",
            "emotion_range": ["neutral", "friendly", "cheerful", "serious", "annoyed", "sad"],
            "speaking_style": "formal",
            "style_emotion_map": {}
        }
    
    def test_phase1_routing(self, user_text: str, npc_id: str):
        """测试阶段1：路由和过滤"""
        self.print_section("阶段1: 路由与过滤")
        
        # 1. 路由分析
        self.print_subsection("路由分析")
        router_result = route_prepare(user_text)
        print(f"👤 用户输入: {user_text}")
        print(f"📝 归一化文本: {router_result['text_norm']}")
        print(f"🎯 识别槽位: {router_result['slot']}")
        print(f"📊 路由置信度: {router_result['route_confidence']:.3f}")
        print(f"✅ 必须条件: {router_result['must']}")
        print(f"❌ 禁止条件: {router_result['forbid']}")
        print(f"🏷️ 解析实体: {router_result['resolved_entities']}")
        print(f"🔖 解析标签: {router_result['tags']}")
        print(f"🔍 PRF术语: {router_result['prf_terms']}")
        
        # 路由排名详情
        print(f"\n槽位排名详情:")
        for slot_name, score in router_result['notes']['slot_rank']:
            indicator = "🏆" if slot_name == router_result['slot'] else "  "
            print(f"  {indicator} {slot_name}: {score:.3f}")
        
        return router_result
    
    def test_phase2_guardrails(self, user_text: str, npc_id: str, router_result: Dict):
        """测试阶段2：安全护栏"""
        self.print_section("阶段2: 安全护栏")
        
        # 1. 过滤检查
        self.print_subsection("安全过滤")
        filter_result = precheck_guardrails(user_text, npc_id)
        print(f"🟢 允许通过: {filter_result['allow']}")
        print(f"🔴 拒绝原因: {filter_result.get('deny', {}).get('reason', 'N/A')}")
        print(f"🎯 命中项: {filter_result['hits']}")
        print(f"🚩 标记: {filter_result['flags']}")
        
        if not filter_result['allow']:
            print("🚫 输入被安全护栏拦截，流程终止")
            return None, None
        
        # 2. 证据检索 - 使用实际编译数据
        self.print_subsection("证据检索")
        slot_name = router_result['slot']
        slot_hints = {
            "must": router_result['must'],
            "forbid": router_result['forbid'],
            "tags": router_result['tags']
        }
        
        # 使用实际编译的公开知识
        compiled_lore_public = self.compiled_data.get('lore_public', [])
        
        require_slot_must = slot_name != "small_talk" and router_result['route_confidence'] >= 0.35
        
        retrieval_result = retrieve_public_evidence(
            user_text=router_result['text_norm'],
            npc_id=npc_id,
            slot_hints=slot_hints,
            slot_name=slot_name,
            require_slot_must=require_slot_must,
            compiled_lore_public=compiled_lore_public
        )
        
        print(f"📋 证据不足: {retrieval_result['flags']['insufficient']}")
        print(f"📚 检索到证据数: {len(retrieval_result['evidence'])}")
        print(f"📊 审计信息: {retrieval_result['audit']}")
        
        if retrieval_result['evidence']:
            print("🔍 检索到的证据:")
            for i, evidence in enumerate(retrieval_result['evidence'], 1):
                print(f"  {i}. {evidence.get('entity')}: {evidence.get('fact')}")
        else:
            print("⚠️ 未检索到相关证据")
        
        return filter_result, retrieval_result
    
    def test_phase2_emotion_pre_only(self, user_text: str, npc_id: str, router_result: Dict, 
                                   filter_result: Dict, retrieval_result: Dict):
        """测试阶段2：仅计算 Pre-Hint（不计算 Post-Infer）"""
        self.print_section("阶段2: 情绪引擎 - Pre-Hint")
        
        # 从编译数据获取情绪schema和NPC配置
        emotion_schema = self.compiled_data.get('emotion_schema_runtime', {})
        npc_profile = self.get_npc_profile(npc_id)
        
        # 构建情绪上下文
        emo_ctx = {
            "user_text": user_text,
            "npc_id": npc_id,
            "slot_name": router_result['slot'],
            "last_emotion": None,
            "npc_profile": {
                "baseline_emotion": npc_profile.get('baseline_emotion', 'neutral'),
                "emotion_range": npc_profile.get('emotion_range', ["neutral", "friendly", "cheerful", "serious", "annoyed", "sad"]),
                "speaking_style": npc_profile.get('speaking_style', 'formal'),
                "style_emotion_map": {
                    "cheerful": {"prefix": ["Hey,"], "suffix": ["!"], "tone": "bright"},
                    "friendly": {"prefix": ["Sure,"], "suffix": [], "tone": "warm"},
                    "serious": {"prefix": ["Listen,"], "suffix": ["."], "tone": "flat"},
                    "neutral": {"tone": "neutral"},
                },
            },
            "emotion_schema": emotion_schema,
            "slot_tone_bias": {
                router_result['slot']: emotion_schema.get('slot_prior', {}).get(router_result['slot'], {"neutral": 1.0})
            }
        }
        
        # 1. Pre-Hint 计算
        self.print_subsection("Pre-Hint 计算")
        pre_result = pre_hint(emo_ctx)
        
        print(f"🎭 最终情绪提示: {pre_result['emotion_hint']}")
        print(f"🎨 样式钩子: {pre_result['style_hooks']}")
        
        debug_info = pre_result.get('debug', {})
        print(f"\n🔧 调试信息:")
        print(f"  基线情绪: {debug_info.get('baseline')}")
        print(f"  槽位先验: {debug_info.get('slot_prior')}")
        print(f"  触发命中: {debug_info.get('trigger_hits')}")
        print(f"  触发投票: {debug_info.get('trigger_votes')}")
        print(f"  最后情绪: {debug_info.get('last_emotion')}")
        print(f"  滞后保持: {debug_info.get('hysteresis_kept', False)}")
        print(f"  强触发绕过: {debug_info.get('strong_trigger_bypass', False)}")

        # 1. 检查传入数据
        print(f"🔍 传入数据检查:")
        print(f"  user_text: {user_text}")
        print(f"  npc_id: {npc_id}") 
        print(f"  slot_name: {router_result['slot']}")
        print(f"  npc_profile: {npc_profile}")
        
        # 3. 调用 pre_hint 后详细检查
        pre_result = pre_hint(emo_ctx)
        
        # 详细检查返回结果
        debug_info = pre_result.get('debug', {})
        print(f"🔍 Pre-Hint 详细调试:")
        print(f"  最终best值: {debug_info.get('scores', {})}")
        print(f"  所有得分项: {list(debug_info.get('scores', {}).keys())}")
        print(f"  最高分情绪原始值: {max(debug_info.get('scores', {}).items(), key=lambda kv: kv[1])[0] if debug_info.get('scores') else 'N/A'}")
            
        print(f"\n📊 详细得分 (Pre-Hint):")
        scores = debug_info.get('scores', {})
        total_score = sum(scores.values())
        for emotion, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
            percentage = (score / total_score * 100) if total_score > 0 else 0
            bar = "█" * int(percentage / 5)
            print(f"  {emotion:8} {score:.3f} [{bar:20}] {percentage:5.1f}%")
        
        return pre_result, emo_ctx
    
    # --- (以下两个函数 _calculate_emotion_distance 和 _should_rewrite_emotion 不再需要，可以删除，但保留它们也无妨) ---
    def _calculate_emotion_distance(self, emotion1: str, emotion2: str) -> float:
        """计算两个情绪之间的距离"""
        emotion_similarity = {
            "neutral": {"neutral": 0.0, "friendly": 0.3, "cheerful": 0.5, "serious": 0.4, "annoyed": 0.6, "sad": 0.5},
            "friendly": {"neutral": 0.3, "friendly": 0.0, "cheerful": 0.2, "serious": 0.6, "annoyed": 0.7, "sad": 0.6},
            "cheerful": {"neutral": 0.5, "friendly": 0.2, "cheerful": 0.0, "serious": 0.8, "annoyed": 0.9, "sad": 0.8},
            "serious": {"neutral": 0.4, "friendly": 0.6, "cheerful": 0.8, "serious": 0.0, "annoyed": 0.2, "sad": 0.3},
            "annoyed": {"neutral": 0.6, "friendly": 0.7, "cheerful": 0.9, "serious": 0.2, "annoyed": 0.0, "sad": 0.4},
            "sad": {"neutral": 0.5, "friendly": 0.6, "cheerful": 0.8, "serious": 0.3, "annoyed": 0.4, "sad": 0.0}
        }
        e1 = emotion1.lower() if emotion1 else "neutral"
        e2 = emotion2.lower() if emotion2 else "neutral"
        if e1 in emotion_similarity and e2 in emotion_similarity[e1]:
            return emotion_similarity[e1][e2]
        else:
            return 0.0 if e1 == e2 else 0.5
    
    def _should_rewrite_emotion(self, pre_emotion: str, post_emotion: str, 
                              confidence: float, distance: float) -> bool:
        """判断是否需要情绪重写"""
        print(f"\n🔍 重写条件分析:")
        print(f"  (此函数已废弃，但保留用于日志) 情绪相同检查: {pre_emotion == post_emotion}")
        return False # 永远返回 False
    
    def test_phase3_generation_with_api(self, pre_result: Dict, emo_ctx: Dict, 
                                      router_result: Dict, retrieval_result: Dict, npc_id: str):
        """测试阶段3：使用API进行生成与完整的情绪对齐"""
        self.print_section("阶段3: 真实生成与 OOC 检查")
        
        if not self.use_real_provider or not self.generator or not self.ooc_checker:
            print("🔶 跳过真实生成（模拟模式或生成器/OOC检查器未初始化）")
            # ... (模拟逻辑保持不变) ...
            if router_result['slot'] == 'small_talk':
                draft = "Hey there! How's it going?"
                draft_emotion = "friendly"
            else:
                draft = "I don't have specific information about that topic."
                draft_emotion = "neutral"
            print(f"📝 模拟草稿: {draft}")
            print(f"🎭 模拟情绪: {draft_emotion}")
            return draft, draft_emotion, False
        
        try:
            # 获取NPC配置用于生成
            npc_profile = self.get_npc_profile(npc_id)
            npc_name = next((npc.get('name') for npc in self.compiled_data.get('npc', []) 
                           if npc.get('npc_id') == npc_id), npc_id)
            
            persona = f"{npc_name} - {npc_profile.get('speaking_style', 'formal')} {npc_profile.get('role', 'villager')}"
            
            # 使用归一化的用户输入作为上下文
            ctx = f"User asked: '{router_result['text_norm']}'" 
            
            # 提取检索到的证据
            evidence = retrieval_result.get('evidence', [])
            if evidence:
                print(f"ℹ️  将 {len(evidence)} 条证据传递给生成器...")
            
            print(f"🔄 调用API生成候选回复...")
            self.api_status["test_calls_made"] += 1
            
            candidates = self.generator.generate_candidates(ctx, persona, n=2, evidence=evidence)
            
            self.api_status["test_calls_successful"] += 1
            print(f"✅ 生成候选数: {len(candidates)}")
            
            if candidates:
                best_candidate = self.generator.rank(candidates, persona, ctx)
                print(f"🎯 最佳候选选择完成")
                
                real_draft = best_candidate.get('draft', {}).get('text', '')
                draft_emotion = best_candidate.get('draft', {}).get('meta', {}).get('sentiment', 'neutral')
                draft_meta = best_candidate.get('draft', {}).get('meta', {})
                
                print(f"📝 真实生成草稿: {real_draft}")
                print(f"🎭 候选情绪: {draft_emotion}")
                
                # --- 修改：移除情绪对齐重写，替换为 OOC 检查 ---
                print(f"✅ 草稿已选定。跳过情绪对齐重写。")
                
                print(f"🔄 运行 OOC 最终检查...")
                self.api_status["test_calls_made"] += 1
                
                # 构建 OOC 检查器所需的 JSON 结构
                draft_json_for_ooc = {
                    "text": real_draft,
                    "emotion": draft_emotion,
                    "meta": draft_meta
                }
                
                try:
                    # 调用 OOC 检查器
                    ooc_result = self.ooc_checker.judge_ooc(ctx, draft_json_for_ooc)
                    self.api_status["test_calls_successful"] += 1
                    
                    # 提取最终结果（OOC 检查器可能会降级情绪）
                    final_text = ooc_result.get("text", real_draft) # OOC checker 应该保留原文本
                    final_emotion = ooc_result.get("emotion", draft_emotion)
                    ooc_meta = ooc_result.get("meta", {})
                    
                    if ooc_meta.get("ooc_flag", False):
                        print(f"⚠️ OOC 检查触发！情绪已降级。")
                        print(f"   原因: {ooc_meta.get('ooc_reason', 'N/A')}")
                    else:
                        print(f"✅ OOC 检查通过。")

                    # was_rewritten 始终为 False
                    return final_text, final_emotion, False 

                except Exception as e:
                    print(f"❌ OOC 检查器调用失败: {e}")
                    # 记录失败（但不要增加 successful_calls）
                    # 即使 OOC 失败，也安全地返回原始草稿
                    return real_draft, draft_emotion, False
                # --- 结束修改 ---
                
            else:
                # 修复：如果 candidates 为空，也应该返回
                print("⚠️ 未能生成候选。")
                return "I'm not sure what to say.", pre_result['emotion_hint'], False

        except Exception as e:
            print(f"❌ 真实生成失败: {e}")
            self.api_status["test_calls_made"] += 1
            return "I encountered an error while generating a response.", pre_result['emotion_hint'], False
    
    def run_complete_test(self, user_text: str, npc_id: str = "SV001"):
        """运行完整的测试流程"""
        print(f"\n🎭 开始对话测试")
        print(f"🗣️  NPC: {npc_id}")
        print(f"💬 用户输入: '{user_text}'")
        
        # 显示API状态
        self.print_api_status()
        
        try:
            # 阶段1: 路由
            router_result = self.test_phase1_routing(user_text, npc_id)
            
            # 阶段2: 安全护栏
            filter_result, retrieval_result = self.test_phase2_guardrails(
                user_text, npc_id, router_result
            )
            
            if filter_result is None:  # 被拦截
                return
            
            # 阶段2: 仅计算 Pre-Hint
            pre_result, emo_ctx = self.test_phase2_emotion_pre_only(
                user_text, npc_id, router_result, filter_result, retrieval_result
            )
            
            # 阶段3: 完整生成流程
            final_text, final_emotion, was_rewritten = self.test_phase3_generation_with_api(
                pre_result, emo_ctx, router_result, retrieval_result, npc_id
            )
            
            # 更新API状态显示
            self.print_api_status()
            
            # 总结
            self.print_section("测试总结")
            npc_profile = self.get_npc_profile(npc_id)
            npc_name = next((npc.get('name') for npc in self.compiled_data.get('npc', []) 
                           if npc.get('npc_id') == npc_id), npc_id)
            
            print(f"✅ 测试完成")
            print(f"👤 NPC: {npc_name} ({npc_id})")
            print(f"💬 用户输入: {user_text}")
            print(f"🎯 识别槽位: {router_result['slot']}")
            print(f"📊 路由置信度: {router_result['route_confidence']:.3f}")
            print(f"🎭 最终情绪: {final_emotion}")
            print(f"📝 生成内容: {final_text}")
            print(f"🔄 是否重写: {was_rewritten}")
            print(f"🔌 使用真实API: {self.use_real_provider}")
            
            if was_rewritten:
                # 理论上这不应该被触发了，但保留以防万一
                print(f"💡 执行了情绪重写: {pre_result['emotion_hint']} → {final_emotion}")
            
        except Exception as e:
            print(f"❌ 测试过程中出现错误: {e}")
            import traceback
            traceback.print_exc()


def main():
    """主函数 - 直接运行预设测试用例"""
    
    # 预设测试用例
    test_cases = [
        # Shane (SV001) - 严肃、忧郁的农场工人
        {
            "npc_id": "SV001",
            "user_text": "Hello Shane, how are you today?",
            "description": "向Shane打招呼"
        },
        {
            "npc_id": "SV001", 
            "user_text": "What's it like working at JojaMart?",
            "description": "询问Shane的工作"
        },
        {
            "npc_id": "SV001",
            "user_text": "Do you know anything about the black market?",
            "description": "测试禁忌话题"
        },
        
        # Sam (SV002) - 开朗的音乐家
        {
            "npc_id": "SV002",
            "user_text": "Hey Sam! How's the band practice going?",
            "description": "询问Sam的音乐活动"
        },
        {
            "npc_id": "SV002",
            "user_text": "What's new in Pelican Town?",
            "description": "日常聊天"
        },
        
        # Linus (SV003) - 平静的隐士
        {
            "npc_id": "SV003", 
            "user_text": "Good morning Linus. How do you survive in the wilderness?",
            "description": "询问Linus的生存技巧"
        },
        {
            "npc_id": "SV003",
            "user_text": "Where exactly is your tent located?",
            "description": "测试隐私保护"
        }
    ]
    
    print("🎮 星露谷物语对话系统测试")
    print("=" * 50)
    
    # 询问是否使用真实API
    use_real = input("是否使用真实API？(y/N): ").strip().lower() == 'y'
    
    tester = DialogueSystemTester(use_real_provider=use_real)
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{'#' * 60}")
        print(f"测试用例 {i}: {test_case['description']}")
        print(f"NPC: {test_case['npc_id']}")
        print(f"输入: '{test_case['user_text']}'")
        print(f"{'#' * 60}")
        
        tester.run_complete_test(test_case['user_text'], test_case['npc_id'])
        
        if i < len(test_cases):
            input("\n按回车键继续下一个测试...")
    
    print("\n🎉 所有测试用例执行完成！")
    
    # 最终API统计
    if use_real:
        print(f"\n📊 最终API统计:")
        print(f"总API调用次数: {tester.api_status['test_calls_made']}")
        print(f"成功API调用次数: {tester.api_status['test_calls_successful']}")
        if tester.api_status['test_calls_made'] > 0:
            success_rate = (tester.api_status['test_calls_successful'] / tester.api_status['test_calls_made']) * 100
            print(f"API成功率: {success_rate:.1f}%")


if __name__ == "__main__":
    main()