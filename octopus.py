#!/usr/bin/env python3
"""
octopus.py — Octopus Agent 主入口
类似 Claude Code 的 AI Agent，基于 Anthropic SDK 的 tool-use 能力。

用法:
    python octopus.py "帮我写一个 Python 斐波那契函数"   # 单次任务
    python octopus.py                                   # 交互模式
    python octopus.py -c                                # 恢复最近会话
    python octopus.py --resume                          # 交互式选择会话
    python octopus.py --resume <name>                   # 按名称恢复
    python octopus.py -n <name>                         # 指定新会话名称
"""

import argparse
import os
import sys

# 将脚本所在目录加入 sys.path，确保模块导入正常
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cli import interactive_mode, setup_signal_handlers
from agent import run_agent
from config import get
from mcp import MCPManager


def main():
    parser = argparse.ArgumentParser(description="Octopus Agent CLI")
    parser.add_argument("task", nargs="*", help="任务描述（单次模式）")
    parser.add_argument("-c", "--continue", dest="continue_session",
                        action="store_true",
                        help="恢复当前目录最近的会话")
    parser.add_argument("-r", "--resume", dest="resume", nargs="?",
                        const="__interactive__", default=None,
                        help="恢复会话：无参数打开选择器，指定名称/ID 恢复")
    parser.add_argument("-n", "--name", dest="session_name", default=None,
                        help="为新会话指定名称")
    parser.add_argument("--stdin", action="store_true",
                        help="从 stdin 读取输入作为任务")

    args = parser.parse_args()

    missing = []
    api_key = get("api_key")
    base_url = get("base_url")
    model = get("model")
    if not api_key:
        missing.append("api_key")
    if not base_url:
        missing.append("base_url")
    if not model:
        missing.append("model")
    if missing:
        print(f"❌ 缺少必配项: {', '.join(missing)}")
        print("   请在 ~/.octopus/config.json 中配置，或设置环境变量：")
        if "api_key" in missing:
            print("   export OCTOPUS_API_KEY=sk-...")
        if "base_url" in missing:
            print("   export OCTOPUS_BASE_URL=https://...")
        if "model" in missing:
            print("   export OCTOPUS_MODEL=model-name")
        sys.exit(1)

    setup_signal_handlers()

    # 启动时清理过期会话
    from session import cleanup_sessions
    from config import get as _get
    period = _get("cleanup_period_days", 30)
    if isinstance(period, int) and period > 0:
        cleanup_sessions(period)

    # 管道输入
    if args.stdin or (not sys.stdin.isatty() and not args.task
                      and not args.continue_session and args.resume is None):
        stdin_text = sys.stdin.read().strip()
        if stdin_text:
            args.task = [stdin_text]

    # 恢复会话
    resume_session_id = None
    if args.continue_session:
        from session import get_latest_session
        resume_session_id = get_latest_session()
        if not resume_session_id:
            print("没有可恢复的会话")
            sys.exit(1)

    elif args.resume is not None:
        from session import find_session_by_name, load_session
        if args.resume == "__interactive__":
            try:
                from tui import session_selector
                resume_session_id = session_selector()
            except ImportError:
                from tui import _session_selector_fallback
                from session import list_sessions
                resume_session_id = _session_selector_fallback(list_sessions())
            if not resume_session_id:
                sys.exit(0)
        else:
            # 按名称/ID 恢复
            from session import load_session
            try:
                load_session(args.resume)
                resume_session_id = args.resume
            except FileNotFoundError:
                found = find_session_by_name(args.resume)
                if found:
                    resume_session_id = found
                else:
                    print(f"未找到会话: {args.resume}")
                    sys.exit(1)

    # 单次任务模式
    if args.task:
        task = " ".join(args.task)
        mcp = MCPManager()
        mcp_configs = get("mcp_servers", {})
        if mcp_configs:
            count = mcp.connect_all(mcp_configs)
            if count:
                print(f"  已连接 {count} 个 MCP 服务器")
        try:
            run_agent(task, mcp=mcp)
        finally:
            mcp.close_all()
    else:
        session_name = args.session_name
        interactive_mode(
            resume_session_id=resume_session_id,
            session_name=session_name,
        )


if __name__ == "__main__":
    main()
