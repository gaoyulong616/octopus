"""子 Agent 工具：在独立线程中运行子任务。"""

import threading

from tools.exceptions import ToolError


def run_sub_agent(task: str, description: str = "",
                  output_fn=None) -> str:
    """在子进程中运行一个独立的子 Agent。"""

    result_holder = {"result": None, "error": None}

    def _run():
        try:
            # 延迟导入避免循环依赖
            from agent import run_agent
            result = run_agent(
                task,
                verbose=False,
                output_fn=output_fn,
            )
            result_holder["result"] = result
        except ToolError:
            raise
        except Exception as e:
            result_holder["error"] = str(e)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=300)  # 5 分钟超时

    if thread.is_alive():
        raise ToolError("子 Agent 超时（300s）")

    if result_holder["error"]:
        raise ToolError(f"子 Agent 错误: {result_holder['error']}")

    return result_holder["result"] or "(子 Agent 无输出)"
