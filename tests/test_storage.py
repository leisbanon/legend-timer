import json
from dataclasses import replace

import pytest

from boss_timer.app import resource_path
from boss_timer.repositories.boss_repository import BossRepository
from boss_timer.repositories.json_store import JsonStore, StorageError
from boss_timer.repositories.profile_repository import ProfileRepository
from boss_timer.services.profile_service import ProfileService


def test_real_config_counts_order_and_edit_round_trip(tmp_path):
    path = tmp_path / "catalog.json"
    repository = BossRepository(path, resource_path())
    definitions = repository.load()
    assert len(definitions) == 311
    assert len({(b.group, b.map) for b in definitions}) == 60
    assert list(dict.fromkeys(b.group for b in definitions)) == ["野外地图", "五小地图", "四大地图", "终极三图"]
    assert definitions[0].map == "藏剑山庄"
    assert len({b.id for b in definitions}) == 311
    assert all(b.sec > 0 for b in definitions)
    definitions[0] = replace(definitions[0], name="编辑后的 BOSS", sec=120, tip="提醒")
    repository.save(definitions)
    reloaded = BossRepository(path, resource_path()).load()
    assert reloaded == definitions
    repository.save_checked(reloaded, {reloaded[0].id})
    assert [b.armed for b in repository.load()].count(True) == 1
    assert path.with_suffix(".json.bak").exists()


def test_invalid_intervals_do_not_break_catalog(tmp_path):
    path = tmp_path / "seed.json"
    path.write_text(json.dumps({"timers": [
        {"name": "无时间"}, {"name": "坏时间", "sec": "x"}, {"name": "负数", "sec": -5},
    ]}), encoding="utf-8")
    assert [b.sec for b in BossRepository(tmp_path / "local.json", path).load()] == [0, 0, 0]


def test_atomic_failure_preserves_original_and_reports_corruption(tmp_path, monkeypatch):
    store = JsonStore(tmp_path / "data.json")
    store.write({"name": "原内容"})

    def reject_replace(*args):
        raise PermissionError("模拟文件占用")

    monkeypatch.setattr("boss_timer.repositories.json_store.os.replace", reject_replace)
    with pytest.raises(StorageError):
        store.write({"name": "新内容"})
    assert store.read() == {"name": "原内容"}
    assert list(tmp_path.glob("*.tmp")) == []
    store.path.write_text("not json", encoding="utf-8")
    with pytest.raises(StorageError):
        store.read()


def test_profile_create_update_save_as_and_persistence(tmp_path, clock):
    repo = ProfileRepository(tmp_path / "profiles.json")
    service = ProfileService(repo, clock)
    first = service.save("打宝路线", [{"id": "one"}])
    clock.advance(10)
    updated = service.save("打宝路线调整", [{"id": "two"}], first.id)
    assert updated.id == first.id
    assert updated.created_at == first.created_at
    assert updated.updated_at > first.updated_at
    copy = service.save("另一条路线", updated.timers)
    assert copy.id != updated.id
    assert repo.load() == [updated, copy]
    with pytest.raises(ValueError):
        service.save("另一条路线", updated.timers)
    with pytest.raises(ValueError):
        service.save("", updated.timers)
    with pytest.raises(ValueError):
        service.save("空列表", [])


def test_profile_write_failure_does_not_commit_memory(tmp_path, monkeypatch, clock):
    repo = ProfileRepository(tmp_path / "profiles.json")
    service = ProfileService(repo, clock)
    first = service.save("路线", [{"id": "one"}])

    def fail(_):
        raise StorageError("保存失败")

    monkeypatch.setattr(repo, "save", fail)
    with pytest.raises(StorageError):
        service.save("新名称", [{"id": "two"}], first.id)
    assert service.profiles == [first]


def test_corrupt_profile_dates_are_reported_before_showing_dialog(tmp_path):
    path = tmp_path / "profiles.json"
    JsonStore(path).write({"profiles": [{"id": "one", "name": "方案", "created_at": "bad",
                                       "updated_at": 1e100, "timers": []}]})
    with pytest.raises(StorageError):
        ProfileRepository(path).load()
