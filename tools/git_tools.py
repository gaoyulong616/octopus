"""Git 工具：worktree 管理、检查点创建/回滚。"""

import os
import re
import subprocess

from tools.bash import get_cwd
from tools.exceptions import ToolError

_SAFE_NAME_RE = re.compile(r'^[a-zA-Z0-9._-]+$')


def run_worktree_create(name: str) -> str:
    """创建 git worktree。"""
    try:
        if not name or not _SAFE_NAME_RE.match(name):
            raise ToolError(f"无效的 worktree 名称: {name}（仅允许字母、数字、点、下划线、连字符）")

        # 检查是否在 git 仓库中
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True, text=True, cwd=get_cwd(), timeout=5,
        )
        if result.returncode != 0:
            raise ToolError("不在 git 仓库中")

        worktree_path = os.path.join(get_cwd(), ".worktrees", name)
        os.makedirs(os.path.dirname(worktree_path), exist_ok=True)

        # 创建 worktree（附带新分支）
        result = subprocess.run(
            ["git", "worktree", "add", worktree_path, "-b", name],
            capture_output=True, text=True, cwd=get_cwd(), timeout=30,
        )
        if result.returncode != 0:
            # 分支可能已存在，尝试用已有分支
            result = subprocess.run(
                ["git", "worktree", "add", worktree_path, name],
                capture_output=True, text=True, cwd=get_cwd(), timeout=30,
            )
            if result.returncode != 0:
                raise ToolError(f"创建 worktree 失败: {result.stderr.strip()[:200]}")

        return f"✓ 已创建 worktree: {worktree_path} (分支: {name})"
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(str(e))


def run_worktree_remove(path: str) -> str:
    """删除 git worktree。"""
    try:
        result = subprocess.run(
            ["git", "worktree", "remove", path],
            capture_output=True, text=True, cwd=get_cwd(), timeout=30,
        )
        if result.returncode != 0:
            # 强制删除
            result = subprocess.run(
                ["git", "worktree", "remove", "--force", path],
                capture_output=True, text=True, cwd=get_cwd(), timeout=30,
            )
            if result.returncode != 0:
                raise ToolError(f"删除 worktree 失败: {result.stderr.strip()[:200]}")
        return f"✓ 已删除 worktree: {path}"
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(str(e))


def run_checkpoint_create(message: str = "auto checkpoint") -> str:
    """创建 git 检查点。"""
    try:
        # 检查是否有未提交的变更
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=get_cwd(), timeout=5,
        )
        if result.returncode != 0:
            raise ToolError("不在 git 仓库中")
        if not result.stdout.strip():
            return "(没有未提交的变更，跳过检查点)"

        # 添加所有变更
        subprocess.run(
            ["git", "add", "-A"],
            capture_output=True, text=True, cwd=get_cwd(), timeout=10,
        )

        # 创建 commit
        result = subprocess.run(
            ["git", "commit", "-m", f"checkpoint: {message}"],
            capture_output=True, text=True, cwd=get_cwd(), timeout=10,
        )
        if result.returncode != 0:
            raise ToolError(f"创建检查点失败: {result.stderr.strip()[:200]}")
        return f"✓ 检查点已创建: {message}"
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(str(e))


def run_checkpoint_rollback() -> str:
    """回滚到上一个检查点。"""
    try:
        # 获取上一个 commit 的消息
        result = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            capture_output=True, text=True, cwd=get_cwd(), timeout=5,
        )
        last_msg = result.stdout.strip()
        if not last_msg.startswith("checkpoint:"):
            raise ToolError("上一个 commit 不是检查点，无法回滚")

        # soft reset 到上一个 commit
        result = subprocess.run(
            ["git", "reset", "--soft", "HEAD~1"],
            capture_output=True, text=True, cwd=get_cwd(), timeout=10,
        )
        if result.returncode != 0:
            raise ToolError(f"回滚失败: {result.stderr.strip()[:200]}")
        return f"✓ 已回滚检查点: {last_msg}"
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(str(e))
