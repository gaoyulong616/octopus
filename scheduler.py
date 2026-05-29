"""自主循环和定时调度器。

提供 ScheduleWakeup 能力，支持 Agent 在空闲时自动继续执行任务。
"""

import threading
import time
from typing import Callable


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

    def cancel(self, name: str) -> bool:
        """取消任务。"""
        with self._lock:
            job = self._jobs.pop(name, None)
            if job and job.get("timer"):
                job["timer"].cancel()
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


# 全局调度器实例
_scheduler: Scheduler | None = None


def get_scheduler() -> Scheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = Scheduler()
    return _scheduler
