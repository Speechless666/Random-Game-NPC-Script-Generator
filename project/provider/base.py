# provider/base.py
from abc import ABC, abstractmethod

class BaseProvider(ABC):
    """统一模型调用接口"""

    @abstractmethod
    def generate(self, prompt: str, schema=None, **kwargs):
        """主生成函数"""
        pass

    @abstractmethod
    def judge(self, context: str, output: str):
        """生成后自评（OOC/情绪检查）"""
        pass

class APIError(Exception):
    """自定义API异常"""
    pass