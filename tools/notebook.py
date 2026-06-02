"""Notebook 编辑工具。"""

import json
import os

from tools.state import get_state
from tools.exceptions import ToolError


def _abs_path(path: str) -> str:
    return get_state().abs_path(path)


def run_notebook_edit(notebook_path: str, new_source: str,
                      cell_id: str | None = None,
                      cell_type: str = "code",
                      edit_mode: str = "replace") -> str:
    try:
        if not os.path.isabs(notebook_path):
            notebook_path = _abs_path(notebook_path)
        if not os.path.exists(notebook_path):
            raise ToolError(f"Notebook 不存在: {notebook_path}")

        with open(notebook_path, encoding="utf-8") as f:
            nb = json.load(f)

        cells = nb.get("cells", [])

        if edit_mode == "delete":
            if cell_id is None:
                raise ToolError("删除模式需要指定 cell_id")
            idx = next((i for i, c in enumerate(cells)
                        if c.get("id") == cell_id), None)
            if idx is None:
                raise ToolError(f"未找到 cell_id: {cell_id}")
            cells.pop(idx)
        elif edit_mode == "insert":
            new_cell = {
                "id": cell_id or f"cell_{len(cells)}",
                "cell_type": cell_type,
                "source": new_source,
                "metadata": {},
            }
            if cell_type == "code":
                new_cell["outputs"] = []
                new_cell["execution_count"] = None
            # 插入到指定 cell_id 之后，否则追加到末尾
            if cell_id:
                idx = next((i for i, c in enumerate(cells)
                            if c.get("id") == cell_id), -1)
                cells.insert(idx + 1, new_cell)
            else:
                cells.append(new_cell)
        else:  # replace
            if cell_id is None:
                raise ToolError("替换模式需要指定 cell_id")
            idx = next((i for i, c in enumerate(cells)
                        if c.get("id") == cell_id), None)
            if idx is None:
                raise ToolError(f"未找到 cell_id: {cell_id}")
            cells[idx]["source"] = new_source
            if cell_type:
                cells[idx]["cell_type"] = cell_type

        nb["cells"] = cells
        with open(notebook_path, "w", encoding="utf-8") as f:
            json.dump(nb, f, ensure_ascii=False, indent=1)
        return f"✓ 已编辑 notebook: {os.path.basename(notebook_path)}"
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(str(e))
