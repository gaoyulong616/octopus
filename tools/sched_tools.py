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

    # 每小时（固定间隔）
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


def _cron_to_next_delay(cron: str) -> int | None:
    """计算从现在到下一次 cron 触发的秒数（用于一次性任务）。"""
    parts = cron.strip().split()
    if len(parts) != 5:
        return None

    minute_str, hour_str, dom, month, dow = parts
    now = __import__("datetime").datetime.now()

    # 解析目标分钟和小时
    if minute_str.isdigit() and hour_str == "*":
        target_minute = int(minute_str)
        # 计算到下一个 target_minute 的延迟
        current_minute = now.minute
        if current_minute < target_minute:
            return (target_minute - current_minute) * 60 - now.second
        else:
            return (60 - current_minute + target_minute) * 60 - now.second

    if minute_str.isdigit() and hour_str.isdigit():
        target_hour = int(hour_str)
        target_minute = int(minute_str)
        target = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
        if target <= now:
            target = target + __import__("datetime").timedelta(days=1)
        return int((target - now).total_seconds())

    # */N 格式回退到间隔方式
    return _cron_to_interval(cron)


def _get_current_session_id() -> str | None:
    """获取当前 agent 上下文的 session_id（用于定时任务绑定）。"""
    try:
        from tools.state import get_state

        return get_state().session_id
    except Exception:
        return None


def _on_wakeup_handler(name, task_prompt, session_id=None, reason=""):
    """定时任务触发时的统一回调：优先走 connection 路由，回退 agent emit / print。"""
    # 1. Web 多会话场景：按 session_id 找对应 bridge 的 event_queue
    if session_id:
        try:
            from web.connection import find_bridge_by_session_id

            bridge = find_bridge_by_session_id(session_id)
            if bridge is not None:
                # 注入到 bridge 的事件队列（前端按 session_id 路由）
                bridge._enqueue({
                    "type": "wakeup",
                    "text": task_prompt or reason,
                    "meta": {"scheduled_name": name},
                })
                return
        except Exception:
            pass

    # 2. 同步 agent emit（agent 在线时）
    try:
        from agent import _get_current_emit

        current_emit = _get_current_emit()
        if current_emit:
            current_emit("wakeup", task_prompt or reason)
            return
    except Exception:
        pass

    # 3. 回退：print
    print(f"\n[定时唤醒] {name}: {task_prompt or reason}")


def run_schedule_wakeup(delay_seconds: int, reason: str = "", prompt: str = "") -> str:
    """安排定时唤醒。"""
    try:
        delay = max(60, min(3600, delay_seconds))  # 限制在 60-3600 秒
        from scheduler import get_scheduler

        sched = get_scheduler()
        session_id = _get_current_session_id()

        def _on_wakeup(name, task_prompt, sid=None):
            _on_wakeup_handler(name, task_prompt, sid, reason)

        name = f"wakeup_{reason[:20]}" if reason else f"wakeup_{int(time.time())}"
        return sched.schedule_once(name, delay, _on_wakeup, prompt, session_id=session_id)
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(str(e))


def run_cron_create(cron: str, prompt: str, name: str, recurring: bool = True) -> str:
    """创建定时任务。"""
    try:
        from scheduler import get_scheduler

        sched = get_scheduler()

        interval = _cron_to_interval(cron)
        if interval is None:
            raise ToolError(f"不支持的 cron 格式: {cron}（支持 */N * * * * 和 N * * * *）")

        session_id = _get_current_session_id()

        def _on_cron(job_name, task_prompt, sid=None):
            _on_wakeup_handler(job_name, task_prompt, sid)

        if recurring:
            return sched.schedule_recurring(name, interval, _on_cron, prompt, session_id=session_id)
        else:
            # 一次性任务：计算到下一次触发时间的精确延迟
            delay = _cron_to_next_delay(cron) or interval
            return sched.schedule_once(name, delay, _on_cron, prompt, session_id=session_id)
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
