import sys
import os

# 添加当前目录到路径
sys.path.append('.')

from provider.qwen import QwenProvider

def test_gemini():
    # 直接初始化 provider，qwen.py 里已经处理了环境变量
    provider = QwenProvider()
    
    # 测试简单文本生成
    print("=== 测试简单文本生成 ===")
    try:
        result = provider.generate("请用一句话介绍你自己")
        print("成功！响应:", result)
    except Exception as e:
        print("失败！错误:", e)
        return False
    
    # 测试 JSON 输出
    print("\n=== 测试 JSON 输出 ===")
    try:
        result = provider.generate(
            "返回一个包含名字和年龄的JSON",
            schema=["name", "age"]
        )
        print("成功！JSON 响应:", result)
    except Exception as e:
        print("失败！错误:", e)
        return False
    
    # 测试 judge 方法
    print("\n=== 测试 judge 方法 ===")
    try:
        result = provider.judge(
            context="你是中世纪骑士",
            output="遵命，我的主人！"
        )
        print("成功！judge 响应:", result)
    except Exception as e:
        print("失败！错误:", e)
        return False
    
    print("\n🎉 所有测试通过！Gemini 调用成功！")
    return True

if __name__ == "__main__":
    test_gemini()