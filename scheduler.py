from __future__ import annotations

"""自主循环和定时调度器。

提供 ScheduleWakeup 能力，支持 Agent 在空闲时自动继续执行任务。
支持持久化：定时任务保存到磁盘，重启后自动恢复。
"""

import inspect
import json
import threading
import time
from pathlib import Path
from typing import Callable


_JOBS_FILE = Path.home() / ".octopus" / "scheduled_jobs.json"


def _invoke_callback(callback: Callable, name: str, prompt: str, session_id: str | None) -> None:
    """智能调用 callback，兼容 (name, prompt) 和 (name, prompt, session_id) 两种签名。

    旧代码（TUI 等外部调用）的 callback 可能只有 2 个参数，新代码（Phase 5 session 绑定）有 3 个。
    """
    try:
        sig = inspect.signature(callback)
        param_count = sum(1 for p in sig.parameters.values()
                          if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD))
        if param_count >= 3:
            callback(name, prompt, session_id)
        else:
            callback(name, prompt)
    except (ValueError, TypeError):
        try:
            callback(name, prompt, session_id)
        except TypeError:
            callback(name, prompt)


class Scheduler:
    """轻量级定时调度器，支持一次性唤醒和周期性任务。"""

    def __init__(self):
        self._jobs: dict[str, dict] = {}
        self._lock = threading.RLock()

    def schedule_once(self, name: str, delay_seconds: int,
                      callback: Callable, prompt: str = "",
                      session_id: str | None = None) -> str:
        """安排一次性任务，delay_seconds 秒后触发。

        session_id: Web 多会话并行活跃场景下，触发时按此查找对应 bridge。
        """
        with self._lock:
            if name in self._jobs:
                self.cancel(name)
            job = {
                "type": "once",
                "delay": delay_seconds,
                "callback": callback,
                "prompt": prompt,
                "session_id": session_id,
                "timer": None,
            }
            timer = threading.Timer(delay_seconds, self._fire, args=[name])
            job["timer"] = timer
            timer.daemon = True
            timer.start()
            self._jobs[name] = job
            self._save()
        return f"已安排: {name} ({delay_seconds}s 后触发)"

    def schedule_recurring(self, name: str, interval_seconds: int,
                           callback: Callable, prompt: str = "",
                           session_id: str | None = None) -> str:
        """安排周期性任务。

        session_id: Web 多会话并行活跃场景下，触发时按此查找对应 bridge。
        """
        with self._lock:
            if name in self._jobs:
                self.cancel(name)
            job = {
                "type": "recurring",
                "interval": interval_seconds,
                "callback": callback,
                "prompt": prompt,
                "session_id": session_id,
                "timer": None,
            }
            self._jobs[name] = job
            self._start_recurring(name)
            self._save()
        return f"已安排周期任务: {name} (每 {interval_seconds}s)"

    def _start_recurring(self, name: str):
        """启动周期性计时器。"""
        job = self._jobs.get(name)
        if not job or job["type"] != "recurring":
            return
        interval = job["interval"]
        timer = threading.Timer(interval, self._fire_recurring, args=[name])
        timer.daemon = True
        timer.start()
        job["timer"] = timer

    def _fire_recurring(self, name: str):
        """触发周期性任务并重新安排。"""
        job = self._jobs.get(name)
        if not job:
            return
        try:
            _invoke_callback(job["callback"], name, job.get("prompt", ""), job.get("session_id"))
        except Exception:
            pass
        # 重新安排
        if name in self._jobs and self._jobs[name]["type"] == "recurring":
            self._start_recurring(name)

    def _fire(self, name: str):
        """触发一次性任务。"""
        job = self._jobs.pop(name, None)
        if not job:
            return
        try:
            _invoke_callback(job["callback"], name, job.get("prompt", ""), job.get("session_id"))
        except Exception:
            pass
        self._save()

    def cancel(self, name: str) -> bool:
        """取消任务。"""
        with self._lock:
            job = self._jobs.pop(name, None)
            if job and job.get("timer"):
                job["timer"].cancel()
            self._save()
            return job is not None

    def list_jobs(self) -> list[dict]:
        """列出所有活跃任务。"""
        with self._lock:
            return [
                {"name": name, "type": job["type"],
                 "interval/delay": job.get("interval") or job.get("delay")}
                for name, job in self._jobs.items()
            ]

    def cancel_all(self):
        """取消所有任务。"""
        with self._lock:
            for job in self._jobs.values():
                if job.get("timer"):
                    job["timer"].cancel()
            self._jobs.clear()
            self._save()

    # ── 持久化 ──

    def _save(self):
        """保存定时任务到磁盘。"""
        try:
            _JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
            serializable = {}
            for name, job in self._jobs.items():
                entry = {
                    "type": job["type"],
                    "prompt": job.get("prompt", ""),
                    "session_id": job.get("session_id"),  # 持久化 session 绑定
                }
                if job["type"] == "once":
                    entry["delay"] = job.get("delay", 0)
                elif job["type"] == "recurring":
                    entry["interval"] = job.get("interval", 0)
                serializable[name] = entry
            _JOBS_FILE.write_text(
                json.dumps(serializable, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    def load(self, callback_factory: Callable | None = None):
        """从磁盘恢复定时任务。

        Args:
            callback_factory: 可选的回调工厂 (name, prompt, session_id) -> callback。
                              如果为 None，使用默认的 print 回调。
        """
        if not _JOBS_FILE.exists():
            return
        try:
            data = json.loads(_JOBS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return

        def _default_callback(name, prompt, session_id=None):
            print(f"\n[定时任务] {name}: {prompt}")

        factory = callback_factory or (lambda n, p, sid=None: _default_callback)

        with self._lock:
            for name, cfg in data.items():
                if name in self._jobs:
                    continue  # 已存在则跳过
                prompt = cfg.get("prompt", "")
                session_id = cfg.get("session_id")
                cb = factory(name, prompt, session_id)

                if cfg["type"] == "recurring":
                    interval = cfg.get("interval", 60)
                    job = {
                        "type": "recurring",
                        "interval": interval,
                        "callback": cb,
                        "prompt": prompt,
                        "session_id": session_id,
                        "timer": None,
                    }
                    self._jobs[name] = job
                    self._start_recurring(name)
                elif cfg["type"] == "once":
                    # 一次性任务重启后不再恢复（已过期）
                    pass


# 全局调度器实例
_scheduler: Scheduler | None = None


def get_scheduler() -> Scheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = Scheduler()
    return _scheduler
