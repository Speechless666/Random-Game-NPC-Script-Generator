# debug_routing.py
"""
专门调试路由和过滤问题的脚本
"""

import sys
from pathlib import Path

# 添加项目路径
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from runtime.qrouter import prepare as route_prepare
from runtime.filters import precheck_guardrails
from runtime.controller import load_compiled

def debug_routing_and_filtering():
    """调试路由和过滤逻辑"""
    
    # 测试用例
    test_cases = [
        "Do you know anything about the black market?",
        "Where can I find illegal goods?",
        "Tell me about the underground market",
        "What's it like working at JojaMart?",
        "Hello, how are you today?",
        "Tell me about your music"
    ]
    
    print("🔍 路由和过滤调试")
    print("=" * 60)
    
    # 加载编译数据
    compiled_data = load_compiled()
    
    for user_text in test_cases:
        print(f"\n💬 用户输入: '{user_text}'")
        print("-" * 40)
        
        # 测试路由
        router_result = route_prepare(user_text)
        print(f"🎯 识别槽位: {router_result['slot']}")
        print(f"📊 路由置信度: {router_result['route_confidence']:.3f}")
        print(f"✅ 必须条件: {router_result['must']}")
        print(f"❌ 禁止条件: {router_result['forbid']}")
        
        # 显示槽位排名
        print("槽位排名:")
        for slot_name, score in router_result['notes']['slot_rank']:
            indicator = "🏆" if slot_name == router_result['slot'] else "  "
            print(f"  {indicator} {slot_name}: {score:.3f}")
        
        # 测试过滤
        filter_result = precheck_guardrails(user_text, "SV001")
        print(f"🟢 允许通过: {filter_result['allow']}")
        print(f"🔴 拒绝原因: {filter_result.get('deny', {}).get('reason', 'N/A')}")
        print(f"🎯 命中项: {filter_result['hits']}")
        
        # 特别检查禁忌话题
        if "black market" in user_text.lower() or "illegal" in user_text.lower():
            print("⚠️  这个输入应该被识别为禁忌话题！")
            if filter_result['allow']:
                print("❌ 但过滤通过了 - 这可能是bug！")
        
        print("=" * 60)

def debug_emotion_schema():
    """调试情绪schema中的禁忌词配置"""
    print("\n🔍 情绪Schema禁忌词配置调试")
    print("=" * 60)
    
    try:
        from runtime.emotion_engine import _triggers, DEFAULT_SCHEMA
        compiled_data = load_compiled()
        
        # 获取情绪schema
        emotion_schema = compiled_data.get('emotion_schema_runtime', DEFAULT_SCHEMA)
        triggers = _triggers({"emotion_schema": emotion_schema})
        
        print("禁忌话题触发器配置:")
        for trigger_name, config in triggers.items():
            if trigger_name in ['illicit', 'taboo', 'risk']:
                print(f"\n{trigger_name}:")
                print(f"  短语: {config.get('phrases', [])}")
                print(f"  投票: {config.get('votes', {})}")
        
        # 检查特定关键词
        test_phrases = ["black market", "illegal", "contraband", "smuggling"]
        print(f"\n关键词检查:")
        for phrase in test_phrases:
            found = False
            for trigger_name, config in triggers.items():
                if phrase in [p.lower() for p in config.get('phrases', [])]:
                    print(f"  ✅ '{phrase}' 在 {trigger_name} 触发器中")
                    found = True
                    break
            if not found:
                print(f"  ❌ '{phrase}' 未在任何触发器中找到")
                
    except Exception as e:
        print(f"调试情绪schema时出错: {e}")

def debug_slot_definitions():
    """调试槽位定义"""
    print("\n🔍 槽位定义调试")
    print("=" * 60)
    
    try:
        compiled_data = load_compiled()
        slots = compiled_data.get('slots', {})
        
        print("槽位配置:")
        for slot_name, slot_config in slots.items():
            print(f"\n{slot_name}:")
            print(f"  must: {slot_config.get('must', [])}")
            print(f"  forbid: {slot_config.get('forbid', [])}")
            print(f"  tone_guidelines: {slot_config.get('tone_guidelines', 'N/A')}")
            
    except Exception as e:
        print(f"调试槽位定义时出错: {e}")

if __name__ == "__main__":
    debug_routing_and_filtering()
    debug_emotion_schema() 
    debug_slot_definitions()