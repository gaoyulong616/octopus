"""统一错误类型：工具执行失败时抛出 ToolError。"""


class ToolError(Exception):
    """工具执行错误。

    工具函数内部 raise ToolError("消息")，
    由 registry.execute_tool 捕获并转为字符串返回给 LLM。
    """

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)
