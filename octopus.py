#!/usr/bin/env python3
"""
octopus.py — Octopus Agent 主入口
类似 Claude Code 的 AI Agent，基于 Anthropic SDK 的 tool-use 能力。

用法:
    python octopus.py "帮我写一个 Python 斐波那契函数"   # 单次任务
    python octopus.py                                   # 交互模式
"""

import os
import sys

# 将脚本所在目录加入 sys.path，确保模块导入正常
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cli import interactive_mode, setup_signal_handlers
from agent import run_agent
from config import get
from mcp import MCPManager


def main():
    api_key = get("api_key")
    if not api_key:
        print("❌ 请先设置环境变量: export OCTOPUS_API_KEY=sk-...")
        print("   或在 .octopus/config.json 中配置 api_key")
        sys.exit(1)

    setup_signal_handlers()

    base_url = get("base_url")
    if base_url:
        print(f"🌐 使用自定义 API 地址: {base_url}")

    if len(sys.argv) > 1:
        task = " ".join(sys.argv[1:])
        # 单次执行模式：连接 MCP，执行任务，清理
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
        interactive_mode()


if __name__ == "__main__":
    main()
