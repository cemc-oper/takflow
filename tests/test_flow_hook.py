"""Regression tests for the generic, instance-local hook registry."""
from __future__ import annotations

from enum import Enum

import pytest

from takflow.flow.hook import BaseHookRegistry, create_hook_decorator


class HookPoint(str, Enum):
    BEFORE = "before"
    AFTER = "after"


@pytest.fixture
def registry() -> BaseHookRegistry:
    return BaseHookRegistry()


def test_execute_orders_by_priority_then_registration(registry):
    calls = []

    def make_hook(name):
        def hook(context):
            calls.append((name, context))
            return name

        return hook

    registry.register(HookPoint.BEFORE, make_hook("default-first"))
    registry.register(HookPoint.BEFORE, make_hook("high"), priority=10)
    registry.register(HookPoint.BEFORE, make_hook("default-second"))
    registry.register(HookPoint.BEFORE, make_hook("highest"), priority=1)
    registry.register(HookPoint.BEFORE, make_hook("high-second"), priority=10)

    results = registry.execute(HookPoint.BEFORE, "context")

    assert results == [
        "highest",
        "high",
        "high-second",
        "default-first",
        "default-second",
    ]
    assert calls == [(name, "context") for name in results]


def test_duplicate_registration_executes_repeatedly_without_consumption(registry):
    calls = []

    def hook(context):
        calls.append(context)
        return len(calls)

    registry.register(HookPoint.BEFORE, hook)
    registry.register(HookPoint.BEFORE, hook)

    assert registry.count_hooks(HookPoint.BEFORE) == 2
    assert registry.execute(HookPoint.BEFORE, "first") == [1, 2]
    assert registry.execute(HookPoint.BEFORE, "second") == [3, 4]
    assert calls == ["first", "first", "second", "second"]


def test_unregister_removes_all_duplicates_and_clear_is_scoped(registry):
    def hook(context):
        return context

    registry.register(HookPoint.BEFORE, hook)
    registry.register(HookPoint.BEFORE, hook, priority=10)
    registry.register(HookPoint.AFTER, hook)

    assert registry.unregister(HookPoint.BEFORE, hook) is True
    assert registry.unregister(HookPoint.BEFORE, hook) is False
    assert not registry.has_hooks(HookPoint.BEFORE)
    assert registry.count_hooks(HookPoint.AFTER) == 1

    registry.register(HookPoint.BEFORE, hook)
    registry.clear(HookPoint.BEFORE)
    assert not registry.has_hooks(HookPoint.BEFORE)
    assert registry.has_hooks(HookPoint.AFTER)

    registry.clear()
    assert registry.count_hooks() == 0


def test_registries_and_hook_points_are_isolated(registry):
    other = BaseHookRegistry()
    registry.register(HookPoint.BEFORE, lambda context: context)

    assert registry.execute(HookPoint.BEFORE, "value") == ["value"]
    assert registry.execute(HookPoint.AFTER, "value") == []
    assert other.execute(HookPoint.BEFORE, "value") == []
    assert other.count_hooks() == 0
    assert registry.count_hooks() == 1


def test_decorator_registers_and_returns_original_function(registry):
    register = create_hook_decorator(lambda: registry)

    @register(HookPoint.BEFORE, priority=20)
    def decorated(context):
        return context + 1

    assert decorated(1) == 2
    assert registry.list_hooks(HookPoint.BEFORE) == {
        "before": [("decorated", 20)]
    }
    assert registry.execute(HookPoint.BEFORE, 1) == [2]


def test_stop_on_error_controls_failure_and_continuation(registry):
    calls = []

    def failing(context):
        calls.append("failing")
        raise ValueError("boom")

    def succeeding(context):
        calls.append("succeeding")
        return "ok"

    registry.register(HookPoint.BEFORE, failing, priority=10)
    registry.register(HookPoint.BEFORE, succeeding, priority=20)

    with pytest.raises(ValueError, match="boom"):
        registry.execute(HookPoint.BEFORE, None)
    assert calls == ["failing"]

    calls.clear()
    assert registry.execute(HookPoint.BEFORE, None, stop_on_error=False) == ["ok"]
    assert calls == ["failing", "succeeding"]
