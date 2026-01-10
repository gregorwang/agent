"""
Dynamic Model Router for DeepSeek Models

Routes queries to appropriate models based on task type:
- deepseek-reasoner (R1): Math, coding, complex reasoning
- deepseek-chat (V3.2): General chat, tool-requiring tasks

IMPORTANT: deepseek-reasoner does NOT support Function Calling/Tools.
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Set
import re


class TaskType(Enum):
    """Enumeration of recognized task types."""
    MATH = "math"              # 数学问题、计算、证明
    CODE = "code"              # 编程、代码生成、调试
    REASONING = "reasoning"    # 复杂推理、逻辑分析
    CHAT = "chat"              # 通用对话、闲聊
    TOOL_USE = "tool_use"      # 需要工具调用的任务


@dataclass
class RoutingDecision:
    """Result of a routing decision."""
    model: str
    task_type: TaskType
    reason: str
    supports_tools: bool
    confidence: float = 1.0  # 0.0 to 1.0


class ModelRouter:
    """
    Intelligent model router that selects the optimal model based on task type.
    
    Routing Strategy:
    - Math/Coding/Reasoning → deepseek-reasoner (R1) for better accuracy
    - Tool-requiring tasks → deepseek-chat (R1 doesn't support tools)
    - General chat → deepseek-chat for faster response
    """
    
    # Model identifiers
    MODEL_REASONER = "deepseek-reasoner"  # R1 - 推理模型
    MODEL_CHAT = "deepseek-chat"          # V3.2 - 通用模型
    
    # 数学相关关键词
    MATH_KEYWORDS: Set[str] = {
        # 中文
        "计算", "数学", "证明", "公式", "方程", "求解", "微积分", "积分",
        "导数", "极限", "概率", "统计", "线性代数", "矩阵", "向量",
        "几何", "三角", "函数", "数列", "级数", "等式", "不等式",
        "因式分解", "开方", "平方", "立方", "对数", "指数",
        # 英文
        "calculate", "math", "prove", "equation", "solve", "calculus",
        "integral", "derivative", "limit", "probability", "statistics",
        "algebra", "matrix", "vector", "geometry", "trigonometry",
    }
    
    # 编程相关关键词
    CODE_KEYWORDS: Set[str] = {
        # 中文
        "代码", "编程", "程序", "调试", "实现", "函数", "算法", "数据结构",
        "类", "对象", "继承", "接口", "重构", "优化代码", "性能优化",
        "单元测试", "测试用例", "bug", "错误", "异常", "报错",
        # 英文
        "code", "programming", "program", "debug", "implement", "function",
        "algorithm", "data structure", "class", "object", "inheritance",
        "interface", "refactor", "optimize", "unit test", "test case",
        # 语言名称
        "python", "java", "javascript", "typescript", "c++", "c#", "rust",
        "go", "golang", "kotlin", "swift", "ruby", "php", "sql", "html", "css",
    }
    
    # 复杂推理关键词
    REASONING_KEYWORDS: Set[str] = {
        # 中文
        "分析", "推理", "逻辑", "论证", "思考", "复杂", "深度分析",
        "因果关系", "推导", "演绎", "归纳", "批判性思维", "评估",
        "比较分析", "优缺点", "权衡", "决策", "策略",
        # 英文
        "analyze", "reasoning", "logic", "argument", "think", "complex",
        "deep analysis", "causality", "deduce", "induction", "critical thinking",
        "evaluate", "compare", "pros and cons", "trade-off", "decision", "strategy",
    }
    
    # 需要工具的关键词（这些任务必须用 chat 模型）
    TOOL_KEYWORDS: Set[str] = {
        # 中文
        "搜索", "查找", "读取文件", "写入文件", "执行", "运行命令",
        "网络", "浏览", "下载", "上传", "API", "调用",
        "最新", "今天", "现在", "实时", "当前",
        # 英文
        "search", "find", "read file", "write file", "execute", "run command",
        "network", "browse", "download", "upload", "api", "call",
        "latest", "today", "now", "real-time", "current",
    }
    
    def __init__(self, default_model: str = None):
        """
        Initialize the router.
        
        Args:
            default_model: Default model to use when no clear match (defaults to chat)
        """
        self.default_model = default_model or self.MODEL_CHAT
        self._enabled = True  # Can be toggled for manual mode
    
    @property
    def enabled(self) -> bool:
        return self._enabled
    
    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = value
    
    def route(self, prompt: str, require_tools: bool = False) -> RoutingDecision:
        """
        Route a prompt to the appropriate model.
        
        Args:
            prompt: User's input prompt
            require_tools: If True, force chat model (for tool-requiring contexts)
        
        Returns:
            RoutingDecision with model choice and reasoning
        """
        if not self._enabled:
            return RoutingDecision(
                model=self.default_model,
                task_type=TaskType.CHAT,
                reason="自动路由已禁用",
                supports_tools=self.default_model == self.MODEL_CHAT
            )
        
        prompt_lower = prompt.lower()
        
        # Priority 1: Check if tools are required
        if require_tools or self._needs_tools(prompt_lower):
            return RoutingDecision(
                model=self.MODEL_CHAT,
                task_type=TaskType.TOOL_USE,
                reason="需要工具调用 → V3.2",
                supports_tools=True,
                confidence=0.9
            )
        
        # Priority 2: Check for math tasks
        if self._is_math(prompt_lower):
            return RoutingDecision(
                model=self.MODEL_REASONER,
                task_type=TaskType.MATH,
                reason="数学问题 → R1推理",
                supports_tools=False,
                confidence=0.85
            )
        
        # Priority 3: Check for coding tasks
        if self._is_code(prompt_lower):
            return RoutingDecision(
                model=self.MODEL_REASONER,
                task_type=TaskType.CODE,
                reason="编程任务 → R1推理",
                supports_tools=False,
                confidence=0.85
            )
        
        # Priority 4: Check for complex reasoning
        if self._is_reasoning(prompt_lower):
            return RoutingDecision(
                model=self.MODEL_REASONER,
                task_type=TaskType.REASONING,
                reason="复杂推理 → R1推理",
                supports_tools=False,
                confidence=0.7
            )
        
        # Default: General chat with V3.2
        return RoutingDecision(
            model=self.MODEL_CHAT,
            task_type=TaskType.CHAT,
            reason="通用对话 → V3.2",
            supports_tools=True,
            confidence=0.6
        )
    
    def _count_keyword_matches(self, text: str, keywords: Set[str]) -> int:
        """Count how many keywords from the set appear in the text."""
        count = 0
        for keyword in keywords:
            if keyword in text:
                count += 1
        return count
    
    def _needs_tools(self, text: str) -> bool:
        """Check if the text indicates a need for tool usage."""
        return self._count_keyword_matches(text, self.TOOL_KEYWORDS) >= 1
    
    def _is_math(self, text: str) -> bool:
        """Check if the text is a math-related task."""
        # Also check for mathematical expressions
        has_math_expr = bool(re.search(r'[\d+\-*/^=<>]+|√|∑|∫|∂|π|∞', text))
        keyword_count = self._count_keyword_matches(text, self.MATH_KEYWORDS)
        return keyword_count >= 1 or has_math_expr
    
    def _is_code(self, text: str) -> bool:
        """Check if the text is a coding-related task."""
        # Also check for code-like patterns
        has_code_pattern = bool(re.search(r'```|def |class |function |import |from |const |let |var ', text))
        keyword_count = self._count_keyword_matches(text, self.CODE_KEYWORDS)
        return keyword_count >= 1 or has_code_pattern
    
    def _is_reasoning(self, text: str) -> bool:
        """Check if the text requires complex reasoning."""
        return self._count_keyword_matches(text, self.REASONING_KEYWORDS) >= 2
    
    def get_model_info(self, model: str) -> dict:
        """Get information about a model."""
        if model == self.MODEL_REASONER:
            return {
                "name": "DeepSeek-R1 (Reasoner)",
                "description": "推理模型，适合数学、编程、复杂分析",
                "supports_tools": False,
                "strengths": ["数学推理", "代码生成", "逻辑分析"],
                "limitations": ["不支持工具调用", "响应较慢"],
            }
        else:
            return {
                "name": "DeepSeek-V3.2 (Chat)",
                "description": "通用对话模型，支持工具调用",
                "supports_tools": True,
                "strengths": ["响应快", "支持工具", "多轮对话"],
                "limitations": ["复杂推理能力相对弱"],
            }


# Singleton instance for easy access
_router_instance: ModelRouter = None


def get_router() -> ModelRouter:
    """Get the singleton ModelRouter instance."""
    global _router_instance
    if _router_instance is None:
        _router_instance = ModelRouter()
    return _router_instance
