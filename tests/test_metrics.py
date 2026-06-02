"""Metrics 模块测试。"""

import json
from pathlib import Path

import pytest

import metrics
from metrics import (estimate_cost_usd, record_call, aggregate,
                     format_stats, timer)


@pytest.fixture(autouse=True)
def tmp_metrics_file(tmp_path, monkeypatch):
    """重定向 metrics 文件到 tmp_path。"""
    target = tmp_path / "metrics.jsonl"
    monkeypatch.setattr(metrics, "_METRICS_FILE", target)
    yield


class TestEstimateCost:
    def test_known_claude_model(self):
        cost = estimate_cost_usd("claude-sonnet-4-5-20250929", 1_000_000, 0)
        # input price 3.0 USD/M
        assert cost == 3.0

    def test_known_opus_with_cache(self):
        cost = estimate_cost_usd("claude-opus-4-5", 1_000_000, 500_000,
                                 cache_read=200_000, cache_write=100_000)
        assert cost > 0
        # Opus output > input price
        assert cost > 3.0

    def test_unknown_model(self):
        assert estimate_cost_usd("bogus-model", 100, 100) == 0.0


class TestRecordCall:
    def test_writes_jsonl(self):
        rec = record_call("abc123", "claude-sonnet-4-5-20250514",
                          input_tokens=100, output_tokens=50)
        assert rec["model"] == "claude-sonnet-4-5-20250514"
        assert rec["input"] == 100
        assert rec["output"] == 50
        # 文件写入
        from metrics import _METRICS_FILE
        with open(_METRICS_FILE) as f:
            line = f.readline()
        data = json.loads(line)
        assert data["input"] == 100
        assert "cost_usd" in data

    def test_session_id_truncated(self):
        rec = record_call("a-very-long-session-id-12345", "claude-haiku-4-5",
                          10, 5)
        # 只保留前 12 位
        assert len(rec["session"]) == 12


class TestAggregate:
    def test_filter_by_session(self):
        record_call("aaa111", "claude-sonnet-4-5", 100, 50)
        record_call("bbb222", "claude-sonnet-4-5", 200, 100)
        agg = aggregate({"session": "aaa"})
        assert agg["calls"] == 1
        assert agg["input"] == 100

    def test_filter_by_model(self):
        record_call("x", "claude-sonnet-4-5", 100, 50)
        record_call("x", "claude-opus-4-5", 200, 100)
        agg = aggregate({"model": "claude-opus-4-5"})
        assert agg["calls"] == 1
        assert agg["input"] == 200

    def test_by_model_breakdown(self):
        record_call("x", "claude-sonnet-4-5", 100, 50)
        record_call("x", "claude-sonnet-4-5", 50, 25)
        agg = aggregate()
        bm = agg["by_model"].get("claude-sonnet-4-5")
        assert bm and bm["calls"] == 2 and bm["input"] == 150


class TestFormatStats:
    def test_empty_when_no_records(self, tmp_path, monkeypatch):
        # 用空路径
        from metrics import _METRICS_FILE
        monkeypatch.setattr(metrics, "_METRICS_FILE", tmp_path / "nonexistent.jsonl")
        text = format_stats()
        assert "暂无" in text

    def test_renders_summary(self):
        record_call("s1", "claude-sonnet-4-5", 1000, 500)
        text = format_stats()
        assert "调用次数" in text
        assert "Tokens" in text
        assert "成本" in text


class TestTimer:
    def test_timer_no_usage_no_record(self):
        with timer("s", "claude-sonnet-4-5") as t:
            pass
        # usage 为空时不应写入
        from metrics import _METRICS_FILE
        if _METRICS_FILE.exists():
            with open(_METRICS_FILE) as f:
                assert f.read() == ""

    def test_timer_with_usage(self):
        with timer("s", "claude-sonnet-4-5") as t:
            t.usage = {"input_tokens": 100, "output_tokens": 50}
        from metrics import _METRICS_FILE
        assert _METRICS_FILE.exists()
