"""文件操作工具：读取、写入、编辑、列表、搜索、复制、移动、删除、图片读取。"""

import base64
import glob as glob_module
import os
import re
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

from tools.state import get_state
from tools.exceptions import ToolError
from constants import MAX_FILE_SIZE as _MAX_FILE_SIZE, MAX_IMAGE_SIZE as _MAX_IMAGE_SIZE


# ── P3: 子目录指令自动注入 ──
# 缓存已注入的子目录指令，避免重复注入
_injected_instructions: set[str] = set()


def _try_inject_subdir_instruction(abs_path: str) -> str:
    """检查文件所在子目录是否有 OCTOPUS.md，若有且未注入过则返回其内容。"""
    # 找到文件的直接父目录
    parent_dir = os.path.dirname(abs_path)
    cwd = get_state().cwd

    # 只注入项目子目录（不是 cwd 本身，不是隐藏目录，不是 .开头的目录）
    if not parent_dir or not parent_dir.startswith(cwd):
        return ""
    if parent_dir == cwd or parent_dir == os.path.dirname(cwd):
        return ""

    rel_dir = os.path.relpath(parent_dir, cwd)
    # 跳过隐藏目录和 .开头的路径段
    if any(part.startswith(".") or part.startswith("__") for part in rel_dir.split(os.sep)):
        return ""

    instruction_file = os.path.join(parent_dir, "OCTOPUS.md")
    cache_key = os.path.abspath(instruction_file)

    if cache_key in _injected_instructions:
        return ""

    if not os.path.isfile(instruction_file):
        return ""

    try:
        with open(instruction_file, encoding="utf-8") as f:
            content = f.read().strip()
        if content:
            _injected_instructions.add(cache_key)
            return f"\n\n---\n[{rel_dir}/OCTOPUS.md 指令（自动注入）]\n{content}\n---"
    except OSError:
        pass
    return ""


def _abs_path(path: str) -> str:
    return get_state().abs_path(path)


def run_read_file(path: str, encoding: str = "utf-8",
                  offset: int | None = None, limit: int | None = None) -> str:
    try:
        abs_path = _abs_path(path)

        # 敏感路径检查（防止 LLM 读取 SSH keys、云凭证、.env 等）
        from tools.security import is_sensitive_path
        if is_sensitive_path(abs_path):
            raise ToolError(
                f"拒绝读取敏感路径: {path}。如需读取，请在 permission_rules 中"
                f"为 read_file 添加显式 allow 规则。"
            )

        size = os.path.getsize(abs_path)

        # offset/limit 模式：按行号读取
        if offset is not None or limit is not None:
            with open(abs_path, encoding=encoding) as f:
                all_lines = f.readlines()
            total_lines = len(all_lines)
            start = max(1, offset or 1) - 1  # 转为 0-indexed
            end = start + limit if limit else total_lines
            if start >= total_lines:
                raise ToolError(f"offset={offset} 超出文件行数（共 {total_lines} 行）")
            selected = all_lines[start:end]
            header = f"(行 {start + 1}-{min(end, total_lines)}/{total_lines})\n"
            return header + "".join(selected)

        if size > _MAX_FILE_SIZE:
            with open(abs_path, encoding=encoding) as f:
                head = f.read(5000)
            return (
                f"[警告] 文件过大 ({size / 1024:.0f}KB)，仅读取前 5000 字符\n\n{head}\n\n"
                f"... (共 {size} 字节)"
            )
        with open(abs_path, encoding=encoding) as f:
            result = f.read()
        # P3: 自动注入子目录指令
        injection = _try_inject_subdir_instruction(abs_path)
        if injection:
            result += injection
        return result
    except ToolError:
        raise
    except FileNotFoundError:
        raise ToolError(f"文件不存在: {path}")
    except Exception as e:
        raise ToolError(str(e))


def run_write_file(path: str, content: str, mode: str = "w") -> str:
    try:
        if len(content.encode("utf-8")) > _MAX_FILE_SIZE:
            raise ToolError(f"内容过大 ({len(content)} 字符)，超过 1MB 限制")
        abs_path = _abs_path(path)
        from tools.security import is_sensitive_path
        if is_sensitive_path(abs_path):
            raise ToolError(f"拒绝写入敏感路径: {path}")
        os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)

        if mode == "a":
            # 追加模式无法原子化，直接写
            with open(abs_path, mode, encoding="utf-8") as f:
                f.write(content)
        else:
            # 覆盖模式：写临时文件再原子 rename
            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=os.path.dirname(abs_path) or ".", prefix=".octopus-", suffix=".tmp"
            )
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    f.write(content)
                os.replace(tmp_path, abs_path)
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        return f"✓ 已写入 {path}（{len(content)} 字符）"
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(str(e))


def run_edit_file(path: str, old_string: str, new_string: str,
                  replace_all: bool = False) -> str:
    try:
        abs_path = _abs_path(path)
        from tools.security import is_sensitive_path
        if is_sensitive_path(abs_path):
            raise ToolError(f"拒绝编辑敏感路径: {path}")
        with open(abs_path, encoding="utf-8") as f:
            content = f.read()

        count = content.count(old_string)
        if count == 0:
            raise ToolError(f"未在 {path} 中找到要替换的文本")
        if count > 1 and not replace_all:
            raise ToolError(
                f"要替换的文本在 {path} 中出现 {count} 次，"
                "请提供更多上下文使其唯一，或设置 replace_all=true"
            )

        if replace_all:
            new_content = content.replace(old_string, new_string)
        else:
            new_content = content.replace(old_string, new_string, 1)

        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=os.path.dirname(abs_path) or ".", prefix=".octopus-", suffix=".tmp"
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(new_content)
            os.replace(tmp_path, abs_path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        # P3: 自动注入子目录指令
        injection = _try_inject_subdir_instruction(abs_path)
        suffix = injection if injection else ""
        return f"✓ 已编辑 {path}（替换了 {count} 处）{suffix}"
    except ToolError:
        raise
    except FileNotFoundError:
        raise ToolError(f"文件不存在: {path}")
    except Exception as e:
        raise ToolError(str(e))


def run_multi_edit(edits: list[dict]) -> str:
    """对多个文件执行批量编辑。"""
    if not edits:
        raise ToolError("edits 列表不能为空")
    results = []
    for i, edit in enumerate(edits):
        path = edit.get("path", "")
        old_string = edit.get("old_string", "")
        new_string = edit.get("new_string", "")
        replace_all = edit.get("replace_all", False)
        if not path:
            results.append(f"  [{i + 1}] 跳过: 缺少 path")
            continue
        try:
            result = run_edit_file(path, old_string, new_string, replace_all)
            results.append(f"  [{i + 1}] {result}")
        except ToolError as e:
            results.append(f"  [{i + 1}] {path}: {e.message}")
    return "\n".join(results)


def run_list_files(path: str = ".", pattern: str = "", recursive: bool = False) -> str:
    from tools.bash import get_cwd
    try:
        target = _abs_path(path)
        if not os.path.isdir(target):
            raise ToolError(f"目录不存在: {path}")

        if pattern:
            if recursive:
                matches = glob_module.glob(
                    os.path.join(target, "**", pattern), recursive=True
                )
            else:
                matches = glob_module.glob(os.path.join(target, pattern))
            results = []
            for m in sorted(matches):
                rel = os.path.relpath(m, get_cwd())
                if os.path.isdir(m):
                    rel += "/"
                results.append(rel)
            if not results:
                return f"在 {path} 中未找到匹配 '{pattern}' 的文件"
            return "\n".join(results)
        else:
            entries = sorted(os.listdir(target))
            results = []
            for entry in entries:
                if os.path.isdir(os.path.join(target, entry)):
                    results.append(f"{entry}/")
                else:
                    results.append(entry)
            if not results:
                return f"目录 {path} 为空"
            return "\n".join(results)
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(str(e))


def _grep_file(filepath: str, regex: re.Pattern, cwd: str) -> list[str]:
    """在单个文件中搜索匹配行。"""
    results = []
    try:
        with open(filepath, encoding="utf-8", errors="ignore") as f:
            for line_no, line in enumerate(f, 1):
                if regex.search(line):
                    rel = os.path.relpath(filepath, cwd)
                    results.append(f"{rel}:{line_no}: {line.rstrip()}")
    except (PermissionError, OSError):
        pass
    return results


def run_grep_search(pattern: str, path: str = ".", include: str = "",
                    max_results: int = 50) -> str:
    from tools.bash import get_cwd
    try:
        target = _abs_path(path)
        try:
            regex = re.compile(pattern)
        except re.error:
            raise ToolError(f"无效的正则表达式: {pattern}")

        if os.path.isfile(target):
            files = [target]
        else:
            if include:
                files = glob_module.glob(
                    os.path.join(target, "**", include), recursive=True
                )
            else:
                files = glob_module.glob(
                    os.path.join(target, "**", "*"), recursive=True
                )
            files = [f for f in files if os.path.isfile(f)]

        if len(files) <= 4:
            # 文件少时直接串行，避免线程开销
            results = []
            for filepath in sorted(files):
                results.extend(_grep_file(filepath, regex, get_cwd()))
                if len(results) >= max_results:
                    results = results[:max_results]
                    break
        else:
            # 文件多时并行搜索
            results = []
            workers = min(8, len(files))
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(_grep_file, f, regex, get_cwd()): f
                    for f in files
                }
                for future in as_completed(futures):
                    results.extend(future.result())
                    if len(results) >= max_results:
                        results = results[:max_results]
                        break

        if not results:
            return f"在 {path} 中未找到匹配 '{pattern}' 的内容"
        header = f"找到 {len(results)} 个结果"
        if len(results) >= max_results:
            header += f"（已截断，最多显示 {max_results} 个）"
        return header + "\n" + "\n".join(results)
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(str(e))


def run_copy_file(source: str, destination: str) -> str:
    try:
        src = _abs_path(source)
        dst = _abs_path(destination)
        from tools.security import is_sensitive_path
        if is_sensitive_path(src) or is_sensitive_path(dst):
            raise ToolError("拒绝操作敏感路径")
        if not os.path.exists(src):
            raise ToolError(f"源文件不存在: {source}")
        if os.path.isdir(src):
            raise ToolError(f"不支持复制目录: {source}")
        dst_dir = os.path.dirname(dst)
        if dst_dir:
            os.makedirs(dst_dir, exist_ok=True)
        shutil.copy2(src, dst)
        return f"已复制: {source} → {destination}"
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"复制失败: {e}")


def run_move_file(source: str, destination: str) -> str:
    try:
        src = _abs_path(source)
        dst = _abs_path(destination)
        from tools.security import is_sensitive_path
        if is_sensitive_path(src) or is_sensitive_path(dst):
            raise ToolError("拒绝移动敏感路径")
        if not os.path.exists(src):
            raise ToolError(f"源文件不存在: {source}")
        dst_dir = os.path.dirname(dst)
        if dst_dir:
            os.makedirs(dst_dir, exist_ok=True)
        shutil.move(src, dst)
        return f"已移动: {source} → {destination}"
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"移动失败: {e}")


def run_delete_file(path: str) -> str:
    try:
        abs_path = _abs_path(path)
        if not os.path.exists(abs_path):
            raise ToolError(f"文件不存在: {path}")
        if os.path.isdir(abs_path):
            raise ToolError(f"不能删除目录，请使用 bash rm 命令: {path}")
        os.remove(abs_path)
        return f"已删除: {path}"
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"删除失败: {e}")


# 支持的图片格式
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def run_read_image(path: str) -> dict:
    """读取图片文件，返回 base64 编码和 MIME 类型。"""
    try:
        abs_path = _abs_path(path)
        if not os.path.exists(abs_path):
            raise ToolError(f"文件不存在: {path}")

        ext = os.path.splitext(abs_path)[1].lower()
        if ext not in _IMAGE_EXTENSIONS:
            raise ToolError(f"不支持的图片格式: {ext}（支持: {', '.join(_IMAGE_EXTENSIONS)}）")

        size = os.path.getsize(abs_path)
        if size > _MAX_IMAGE_SIZE:
            raise ToolError(f"图片过大 ({size / 1024 / 1024:.1f}MB)，超过 {_MAX_IMAGE_SIZE // 1024 // 1024}MB 限制")

        with open(abs_path, "rb") as f:
            data = f.read()

        b64 = base64.b64encode(data).decode("ascii")
        mime = _IMAGE_MIME.get(ext, "image/png")
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": mime,
                "data": b64,
            },
        }
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(str(e))
