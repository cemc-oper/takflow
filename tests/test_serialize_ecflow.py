"""Tests for takflow.backends.ecflow.serializer (folded light-ecflow + new features)."""
from __future__ import annotations

import pytest

from takflow.backends.ecflow.serializer import (
    Clock,
    Defs,
    DState,
    Family,
    InLimit,
    Late,
    RepeatDay,
    Suite,
    Task,
)


def test_suite_family_task_round_trip():
    suite = Suite("s1")
    fam = Family("f1")
    task = Task("t1")
    fam.add_task(task)
    suite.add_family(fam)
    suite.add_variable("FOO", "bar")
    text = Defs(suite).to_def()
    assert "suite s1" in text
    assert "family f1" in text
    assert "task t1" in text
    assert "edit FOO 'bar'" in text
    assert text.count("endsuite") == 1
    assert text.count("endfamily") == 1


def test_inlimit_tokens_emitted():
    suite = Suite("s1")
    suite.add_inlimit("/s1/my_limit", tokens=3)
    text = Defs(suite).to_def()
    assert "inlimit /s1/my_limit 3" in text


def test_repeat_day_with_real_clock():
    suite = Suite("s1")
    suite.add_clock(Clock("real", "12:00"))
    suite.add_repeat(RepeatDay(1))
    text = Defs(suite).to_def()
    assert "clock real 12:00" in text
    assert "repeat day 1" in text


def test_late_submitted_complete_relative():
    task = Task("t1")
    task.add_late(Late().submitted(0, 10).complete(0, 30, relative=True))
    text = Defs(Suite("s1")).to_def()
    assert "late" not in text  # late is on the task, not the empty suite
    task_text = "\n".join(task.to_def(0))
    assert "late -s 00:10 -c +00:30" in task_text


def test_late_active_complete_absolute():
    task = Task("t1")
    task.add_late(
        Late()
        .submitted(1, 0)
        .active(2, 30, relative=False)
        .complete(3, 0, relative=False)
    )
    task_text = "\n".join(task.to_def(0))
    assert "late -s 01:00 -a 02:30 -c 03:00" in task_text


def test_defstatus_complete():
    suite = Suite("s1")
    suite.add_defstatus(DState.complete)
    text = Defs(suite).to_def()
    assert "defstatus complete" in text
