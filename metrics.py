"""Metrics 持久化：记录每次 LLM API 调用的 token 用量、延迟、估算成本。

格式：~/.octopus/metrics.jsonl，每行一条 JSON。
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

_METRICS_FILE = Path.home() / ".octopus" / "metrics.jsonl"

# 各模型每百万 token 的价格（美元）。仅作估算，可能与供应商实际计费有出入。
# 复用 Claude Code 公开价格 + DeepSeek 公开价格。
_PRICING_USD_PER_MTOKEN: dict[str, dict[str, float]] = {
    # Claude 4.x 系列
    "claude-opus-4": {"input": 15.0, "output": 75.0, "cache_read": 1.5, "cache_write": 18.75},
    "claude-sonnet-4": {"input": 3.0, "output": 15.0, "cache_read": 0.3, "cache_write": 3.75},
    "claude-haiku-4": {"input": 1.0, "output": 5.0, "cache_read": 0.1, "cache_write": 1.25},
    # Claude 3.x 系列
    "claude-3-5-sonnet": {"input": 3.0, "output": 15.0},
    "claude-3-5-haiku": {"input": 0.8, "output": 4.0},
    "claude-3-opus": {"input": 15.0, "output": 75.0},
    "claude-3-haiku": {"input": 0.25, "output": 1.25},
    # DeepSeek（默认 v4）
    "deepseek-v4": {"input": 1.1, "output": 2.8},
    "deepseek-v4-pro": {"input": 2.4, "output": 9.9},
    "deepseek-v4-flash": {"input": 0.4, "output": 1.0},
}


def _find_pricing(model: str) -> dict[str, float]:
    """模糊匹配模型价格。"""
    if model in _PRICING_USD_PER_MTOKEN:
        return _PRICING_USD_PER_MTOKEN[model]
    model_lower = model.lower()
    for key, price in _PRICING_USD_PER_MTOKEN.items():
        if key in model_lower:
            return price
    # 检查日期后缀（如 claude-sonnet-4-20250514），去掉后重试
    base = model_lower.rsplit("-", 1)[0] if "-" in model_lower else model_lower
    for key, price in _PRICING_USD_PER_MTOKEN.items():
        if key == base or key in base:
            return price
    return {}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int,
                      cache_read: int = 0, cache_write: int = 0) -> float:
    """根据模型价格估算单次调用成本（美元）。"""
    pricing = _find_pricing(model)
    if not pricing:
        return 0.0
    cost = (
        input_tokens / 1_000_000 * pricing.get("input", 0.0)
        + output_tokens / 1_000_000 * pricing.get("output", 0.0)
        + cache_read / 1_000_000 * pricing.get("cache_read", pricing.get("input", 0.0) * 0.1)
        + cache_write / 1_000_000 * pricing.get("cache_write", pricing.get("input", 0.0) * 1.25)
    )
    return round(cost, 6)


def record_call(session_id: str | None, model: str,
                input_tokens: int, output_tokens: int,
                cache_read: int = 0, cache_write: int = 0,
                latency_ms: float = 0.0) -> dict[str, Any]:
    """记录一次 LLM 调用，返回记录字典。"""
    record = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "session": (session_id or "")[:12],
        "model": model,
        "input": int(input_tokens),
        "output": int(output_tokens),
        "cache_read": int(cache_read),
        "cache_write": int(cache_write),
        "latency_ms": int(latency_ms),
        "cost_usd": estimate_cost_usd(model, input_tokens, output_tokens,
                                       cache_read, cache_write),
    }
    try:
        _METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_METRICS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return record


def _iter_records(path: Path | None = None) -> Iterable[dict]:
    """迭代 metrics 文件中的每条记录。"""
    target = path or _METRICS_FILE
    if not target.exists():
        return
    try:
        with open(target, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass


# typing.Iterable（避免循环导入麻烦，独立 import）
from typing import Iterable  # noqa: E402


def aggregate(filters: dict | None = None) -> dict[str, Any]:
    """聚合查询 metrics。

    filters 支持：
      - session: 仅该 session_id（前 12 位匹配）
      - model:   仅该 model
      - since:   ISO datetime 字符串，仅此之后
    """
    filters = filters or {}
    total = {"calls": 0, "input": 0, "output": 0,
             "cache_read": 0, "cache_write": 0,
             "cost_usd": 0.0, "latency_ms_total": 0,
             "by_model": {}}
    since = filters.get("since")
    for rec in _iter_records():
        if filters.get("session") and not rec.get("session", "").startswith(filters["session"]):
            continue
        if filters.get("model") and rec.get("model") != filters["model"]:
            continue
        if since and rec.get("ts", "") < since:
            continue
        total["calls"] += 1
        total["input"] += rec.get("input", 0)
        total["output"] += rec.get("output", 0)
        total["cache_read"] += rec.get("cache_read", 0)
        total["cache_write"] += rec.get("cache_write", 0)
        total["cost_usd"] += rec.get("cost_usd", 0.0)
        total["latency_ms_total"] += rec.get("latency_ms", 0)
        m = rec.get("model", "?")
        bm = total["by_model"].setdefault(m, {"calls": 0, "input": 0, "output": 0, "cost_usd": 0.0})
        bm["calls"] += 1
        bm["input"] += rec.get("input", 0)
        bm["output"] += rec.get("output", 0)
        bm["cost_usd"] += rec.get("cost_usd", 0.0)
    return total


def format_stats(filters: dict | None = None) -> str:
    """格式化为人类可读的统计文本。"""
    agg = aggregate(filters)
    if agg["calls"] == 0:
        return "暂无调用记录（~/.octopus/metrics.jsonl 不存在或为空）"
    avg_lat = agg["latency_ms_total"] / agg["calls"] if agg["calls"] else 0

    # 缓存命中率：cache_read / (cache_read + input + cache_write)
    total_input_equiv = agg["input"] + agg["cache_read"] + agg["cache_write"]
    cache_hit_rate = (agg["cache_read"] / total_input_equiv * 100) if total_input_equiv > 0 else 0.0
    # 缓存节省：如果不缓存，所有 cache_read+cache_write 都按 input 计费
    # 简化估算：节省 = cache_read × (input_price - cache_read_price) + cache_write 避免的重复计费
    cache_saved_ratio = (agg["cache_read"] / (agg["cache_read"] + agg["input"]) * 100) if (agg["cache_read"] + agg["input"]) > 0 else 0.0

    lines = [
        f"调用次数: {agg['calls']}",
        f"Tokens: input={agg['input']:,}  output={agg['output']:,}  "
        f"cache_read={agg['cache_read']:,}  cache_write={agg['cache_write']:,}",
        f"缓存命中率: {cache_hit_rate:.1f}%  （重复读取占输入比例: {cache_saved_ratio:.1f}%）",
        f"估算成本: ${agg['cost_usd']:.4f} USD",
        f"平均延迟: {avg_lat:.0f} ms",
    ]
    if agg["by_model"]:
        lines.append("\n按模型分布:")
        for m, st in sorted(agg["by_model"].items(), key=lambda x: -x[1]["calls"]):
            lines.append(
                f"  {m}: {st['calls']} 次, "
                f"in={st['input']:,} out={st['output']:,}, "
                f"${st['cost_usd']:.4f}"
            )
    return "\n".join(lines)


# ── 上下文管理器：方便在 agent.py 包裹 API 调用计时 ──

class _CallTimer:
    """简易计时器：with 块退出时自动记录 metrics。"""

    def __init__(self, session_id: str | None, model: str):
        self.session_id = session_id
        self.model = model
        self.start = 0.0
        self.usage: dict[str, int] = {}

    def __enter__(self):
        self.start = time.monotonic()
        return self

    def __exit__(self, exc_type, exc, tb):
        if not self.usage:
            return False
        latency_ms = (time.monotonic() - self.start) * 1000
        record_call(
            session_id=self.session_id,
            model=self.model,
            input_tokens=self.usage.get("input_tokens", 0),
            output_tokens=self.usage.get("output_tokens", 0),
            cache_read=self.usage.get("cache_read", 0),
            cache_write=self.usage.get("cache_write", 0),
            latency_ms=latency_ms,
        )
        return False


def timer(session_id: str | None, model: str) -> _CallTimer:
    """用法：

        with metrics.timer(session_id, model) as t:
            resp = ...
            t.usage = {"input_tokens": ..., "output_tokens": ..., ...}
    """
    return _CallTimer(session_id, model)
