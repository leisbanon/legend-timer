from dataclasses import replace

import pytest

from boss_timer.domain.models import BossDefinition, TimerState
from boss_timer.services.timer_service import DuplicateBossError, TimerError, TimerService


def boss(name="雷炎蛛王", sec=1800, map_name="藏剑山庄", boss_id="boss-1"):
    return BossDefinition(boss_id, "野外地图", map_name, name, sec, name)


def test_duplicate_names_across_maps_and_missing_interval(clock):
    service = TimerService(clock)
    entry = service.start(boss())
    clock.advance(100)
    with pytest.raises(DuplicateBossError):
        service.start(boss(map_name="魔龙殿", boss_id="boss-2"))
    assert entry.remaining(clock()) == 1700
    with pytest.raises(TimerError):
        service.start(boss(name="未配置怪物", sec=0))
    assert len(service.entries) == 1


@pytest.mark.parametrize("state", ["running", "paused", "expired"])
def test_restart_uses_full_interval_and_preserves_identity(clock, state):
    service = TimerService(clock)
    entry = service.start(boss(sec=60))
    clock.advance(20)
    if state == "paused":
        service.pause(entry.id)
    elif state == "expired":
        clock.advance(50)
    assert service.restart(entry.id)
    assert entry.deadline == clock() + 60
    assert entry.paused_remaining is None
    assert entry.state(clock()) == TimerState.RUNNING
    assert list(service.entries) == [entry.id]


def test_pause_resume_does_not_count_time_while_paused(clock):
    service = TimerService(clock)
    entry = service.start(boss(sec=60))
    clock.advance(10.25)
    assert service.pause(entry.id)
    clock.advance(3600)
    assert entry.remaining(clock()) == 49.75
    assert not service.pause(entry.id)
    assert service.cleanup() == []
    assert service.resume(entry.id)
    assert entry.deadline == clock() + 49.75
    assert not service.resume(entry.id)
    clock.advance(49.74)
    assert entry.display_seconds(clock()) == 1
    clock.advance(0.02)
    assert entry.state(clock()) == TimerState.EXPIRED
    assert not service.pause(entry.id)


def test_expiry_boundary_and_stable_sorting(clock):
    service = TimerService(clock)
    slow = service.start(boss(sec=100))
    fast = service.start(boss("魔龙教主", sec=10, boss_id="boss-2"))
    same = service.start(boss("恶魔树妖", sec=10, boss_id="boss-3"))
    assert [e.id for e in service.sorted_entries()] == [fast.id, same.id, slow.id]
    clock.advance(10)
    assert fast.display_seconds(clock()) == 0
    assert service.cleanup() == []
    clock.advance(119.999)
    assert service.cleanup() == []
    clock.advance(0.001)
    assert service.cleanup() == [fast.id, same.id]
    assert list(service.entries) == [slow.id]


def test_all_start_resumes_and_does_not_reset_or_duplicate(clock):
    service = TimerService(clock)
    one = boss(sec=100)
    entry = service.start(one)
    clock.advance(5)
    service.pause_all()
    clock.advance(100)
    assert service.start_all() == 1
    assert len(service.entries) == 1
    assert entry.remaining(clock()) == 95
    deadline = entry.deadline
    assert service.start_all() == 0
    assert entry.deadline == deadline


def test_edit_updates_metadata_without_resetting_timer(clock):
    service = TimerService(clock)
    definition = boss()
    entry = service.start(definition)
    original_deadline = entry.deadline
    updated = replace(definition, name="新名字", sec=3600, tip="提示内容")
    service.sync_definition(updated)
    assert (entry.name, entry.sec, entry.tip) == ("新名字", 3600, "提示内容")
    assert entry.deadline == original_deadline
    service.start(boss("魔龙教主", boss_id="boss-2"))
    with pytest.raises(TimerError):
        service.sync_definition(replace(updated, name="魔龙教主"))
    assert entry.name == "新名字"


def test_restore_running_and_paused_and_clear_old_expiries(clock):
    original = TimerService(clock)
    running = original.start(boss(sec=100))
    paused = original.start(boss("魔龙教主", sec=60, boss_id="boss-2"))
    original.pause(paused.id)
    payload = original.snapshot()
    clock.advance(50)
    restored = TimerService(clock)
    assert restored.restore(payload, []) == 0
    assert restored.entries[running.id].remaining(clock()) == 50
    assert restored.entries[paused.id].remaining(clock()) == 60
    clock.advance(170)
    assert restored.restore(payload, []) == 1
    assert list(restored.entries) == [paused.id]


def test_restore_is_transactional_and_uses_latest_names(clock):
    service = TimerService(clock)
    entry = service.start(boss())
    payload = service.snapshot()
    assert service.restore(payload, [replace(boss(), name="新版名称")]) == 0
    assert service.entries[entry.id].name == "新版名称"
    for invalid in [
        [*payload, payload[0]],
        [{**payload[0], "deadline": float("nan")}],
        [{**payload[0], "deadline": 1e100}],
        [{**payload[0], "paused_remaining": -1}],
        [{"unknown": "bad"}],
    ]:
        with pytest.raises(TimerError):
            service.restore(invalid, [])
        assert len(service.entries) == 1
        assert service.entries[entry.id].name == "新版名称"


def test_all_running_rows_are_saved(clock):
    service = TimerService(clock)
    entry = service.start(boss())
    entry.selected = False
    assert service.snapshot() == [entry.to_dict()]
    assert len(service.entries) == 1
