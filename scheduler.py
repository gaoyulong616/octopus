from __future__ import annotations

"""自主循环和定时调度器。

提供 ScheduleWakeup 能力，支持 Agent 在空闲时自动继续执行任务。
支持持久化：定时任务保存到磁盘，重启后自动恢复。
"""

import json
import threading
import time
from pathlib import Path
from typing import Callable


_JOBS_FILE = Path.home() / ".octopus" / "scheduled_jobs.json"


class Scheduler:
    """轻量级定时调度器，支持一次性唤醒和周期性任务。"""

    def __init__(self):
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def schedule_once(self, name: str, delay_seconds: int,
                      callback: Callable, prompt: str = "") -> str:
        """安排一次性任务，delay_seconds 秒后触发。"""
        with self._lock:
            if name in self._jobs:
                self.cancel(name)
            job = {
                "type": "once",
                "delay": delay_seconds,
                "callback": callback,
                "prompt": prompt,
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
                           callback: Callable, prompt: str = "") -> str:
        """安排周期性任务。"""
        with self._lock:
            if name in self._jobs:
                self.cancel(name)
            job = {
                "type": "recurring",
                "interval": interval_seconds,
                "callback": callback,
                "prompt": prompt,
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
            job["callback"](name, job.get("prompt", ""))
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
            job["callback"](name, job.get("prompt", ""))
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
            callback_factory: 可选的回调工厂 (name, prompt) -> callback。
                              如果为 None，使用默认的 print 回调。
        """
        if not _JOBS_FILE.exists():
            return
        try:
            data = json.loads(_JOBS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return

        def _default_callback(name, prompt):
            print(f"\n[定时任务] {name}: {prompt}")

        factory = callback_factory or (lambda n, p: _default_callback)

        with self._lock:
            for name, cfg in data.items():
                if name in self._jobs:
                    continue  # 已存在则跳过
                prompt = cfg.get("prompt", "")
                cb = factory(name, prompt)

                if cfg["type"] == "recurring":
                    interval = cfg.get("interval", 60)
                    job = {
                        "type": "recurring",
                        "interval": interval,
                        "callback": cb,
                        "prompt": prompt,
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
