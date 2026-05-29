"""调度器测试。"""

import time

import pytest

from scheduler import Scheduler


class TestScheduler:
    def test_schedule_once(self):
        results = []
        sched = Scheduler()

        def cb(name, prompt):
            results.append((name, prompt))

        sched.schedule_once("test", 1, cb, "hello")
        time.sleep(1.5)
        assert len(results) == 1
        assert results[0] == ("test", "hello")

    def test_cancel(self):
        results = []
        sched = Scheduler()

        def cb(name, prompt):
            results.append(name)

        sched.schedule_once("cancel_me", 1, cb)
        sched.cancel("cancel_me")
        time.sleep(1.5)
        assert len(results) == 0

    def test_list_jobs(self):
        sched = Scheduler()

        def cb(name, prompt):
            pass

        sched.schedule_once("job1", 60, cb)
        sched.schedule_once("job2", 120, cb)
        jobs = sched.list_jobs()
        assert len(jobs) == 2
        sched.cancel_all()

    def test_cancel_all(self):
        results = []
        sched = Scheduler()

        def cb(name, prompt):
            results.append(name)

        sched.schedule_once("j1", 1, cb)
        sched.schedule_once("j2", 1, cb)
        sched.cancel_all()
        time.sleep(1.5)
        assert len(results) == 0


class TestCronParser:
    def test_every_5_minutes(self):
        from tools import _cron_to_interval
        assert _cron_to_interval("*/5 * * * *") == 300

    def test_every_hour(self):
        from tools import _cron_to_interval
        assert _cron_to_interval("0 * * * *") == 3600

    def test_every_2_hours(self):
        from tools import _cron_to_interval
        assert _cron_to_interval("0 */2 * * *") == 7200

    def test_invalid(self):
        from tools import _cron_to_interval
        assert _cron_to_interval("invalid") is None
