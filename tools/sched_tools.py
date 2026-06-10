"""调度工具：定时唤醒、周期性定时任务。"""

import time

from tools.exceptions import ToolError


def _cron_to_interval(cron: str) -> int | None:
    """将简单的 cron 表达式转换为秒级间隔。

    支持格式：
    - */N * * * * → N * 60 秒
    - N * * * * → 3600 秒（每小时第 N 分钟）
    - 0 N * * * → 每 N 小时
    """
    parts = cron.strip().split()
    if len(parts) != 5:
        return None

    minute, hour, dom, month, dow = parts

    def _valid_range(field: str, low: int, high: int) -> bool:
        """校验 cron 字段值是否在合法范围内。"""
        if field == "*":
            return True
        if field.startswith("*/"):
            try:
                n = int(field[2:])
                return low <= n <= high
            except ValueError:
                return False
        if field.isdigit():
            return low <= int(field) <= high
        return True  # 逗号/连字符等复杂格式暂放行

    # */N 分钟
    if minute.startswith("*/") and hour == "*":
        if not _valid_range(minute, 1, 59):
            return None
        try:
            n = int(minute[2:])
            return n * 60
        except ValueError:
            return None

    # 每小时
    if hour == "*" and minute.isdigit():
        if not _valid_range(minute, 0, 59):
            return None
        return 3600

    # 每 N 小时
    if hour.startswith("*/") and minute.isdigit():
        if not _valid_range(hour, 1, 23) or not _valid_range(minute, 0, 59):
            return None
        try:
            n = int(hour[2:])
            return n * 3600
        except ValueError:
            return None

    # 每天
    if dom == "*" and month == "*" and dow == "*":
        if hour.isdigit() and minute.isdigit():
            if not _valid_range(hour, 0, 23) or not _valid_range(minute, 0, 59):
                return None
            return 86400  # 24h

    return None


def run_schedule_wakeup(delay_seconds: int, reason: str = "",
                        prompt: str = "") -> str:
    """安排定时唤醒。"""
    try:
        delay = max(60, min(3600, delay_seconds))  # 限制在 60-3600 秒
        from scheduler import get_scheduler
        sched = get_scheduler()

        def _on_wakeup(name, task_prompt):
            # 优先通过 agent emit 推送（Web UI / TUI），回退 print
            from agent import _current_emit
            if _current_emit:
                _current_emit("wakeup", task_prompt or reason)
            else:
                print(f"\n[定时唤醒] {name}: {task_prompt or reason}")

        name = f"wakeup_{reason[:20]}" if reason else f"wakeup_{int(time.time())}"
        return sched.schedule_once(name, delay, _on_wakeup, prompt)
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(str(e))


def run_cron_create(cron: str, prompt: str, name: str,
                    recurring: bool = True) -> str:
    """创建定时任务。"""
    try:
        from scheduler import get_scheduler
        sched = get_scheduler()

        interval = _cron_to_interval(cron)
        if interval is None:
            raise ToolError(f"不支持的 cron 格式: {cron}（支持 */N * * * * 和 N * * * *）")

        def _on_cron(job_name, task_prompt):
            print(f"\n[定时任务] {job_name}: {task_prompt}")

        if recurring:
            return sched.schedule_recurring(name, interval, _on_cron, prompt)
        else:
            return sched.schedule_once(name, interval, _on_cron, prompt)
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(str(e))


def run_cron_delete(name: str) -> str:
    """取消定时任务。"""
    from scheduler import get_scheduler
    sched = get_scheduler()
    if sched.cancel(name):
        return f"✓ 已取消定时任务: {name}"
    return f"[错误] 未找到定时任务: {name}"


def run_cron_list() -> str:
    """列出所有定时任务。"""
    from scheduler import get_scheduler
    sched = get_scheduler()
    jobs = sched.list_jobs()
    if not jobs:
        return "没有活跃的定时任务"
    lines = [f"活跃定时任务 ({len(jobs)} 个):"]
    for j in jobs:
        interval = j.get("interval/delay", "?")
        lines.append(f"  {j['name']}: {j['type']}, {interval}s")
    return "\n".join(lines)
