import json
from dataclasses import replace

import pytest

from boss_timer.app import catalog_path, resource_path
from boss_timer.repositories.boss_repository import BossRepository
from boss_timer.repositories.json_store import JsonStore, StorageError
from boss_timer.repositories.profile_repository import ProfileRepository
from boss_timer.services.profile_service import ProfileService
from boss_timer.services.local_data import clear_local_config, migrate_local_data


def test_source_catalog_uses_local_cache(tmp_path):
    assert catalog_path(tmp_path) == tmp_path / "boss_catalog.json"


def test_local_edits_override_seed_and_do_not_modify_defaults(tmp_path):
    config = tmp_path / "boss_config.json"
    JsonStore(config).write({"timers": [{"name": "测试", "sec": 1800}]})
    repository = BossRepository(catalog_path(tmp_path), config)
    bosses = repository.load()
    repository.save([replace(bosses[0], sec=15)])
    assert BossRepository(catalog_path(tmp_path), config).load()[0].sec == 15
    assert JsonStore(config).read()["timers"][0]["sec"] == 1800


def test_migration_preserves_new_data_and_copies_missing_files(tmp_path):
    legacy = tmp_path / "LegendBossTimer"
    JsonStore(legacy / "boss_catalog.json").write({"source": "old"})
    JsonStore(legacy / "profiles.json").write({"profiles": []})
    JsonStore(tmp_path / "boss_catalog.json").write({"source": "new"})
    migrate_local_data(tmp_path, legacy)
    assert JsonStore(tmp_path / "boss_catalog.json").read() == {"source": "new"}
    assert JsonStore(tmp_path / "profiles.json").read() == {"profiles": []}
    assert (legacy / "boss_catalog.json").exists()


def test_reset_cleans_both_directories_and_backups_but_keeps_defaults_and_log(tmp_path):
    legacy = tmp_path / "LegendBossTimer"
    for directory in (tmp_path, legacy):
        for name in ("boss_catalog.json", "profiles.json", "settings.json"):
            store = JsonStore(directory / name)
            store.write({"old": True})
            store.write({"old": False})
    JsonStore(tmp_path / "boss_config.json").write({"default": True})
    (tmp_path / "app.log").touch()
    (tmp_path / "boss_catalog-test.tmp").touch()
    clear_local_config(tmp_path, legacy)
    assert not list(tmp_path.rglob("*.json.bak"))
    assert not list(tmp_path.rglob("*.tmp"))
    assert list(tmp_path.rglob("*.json")) == [tmp_path / "boss_config.json"]
    assert (tmp_path / "app.log").exists()


def test_reset_move_failure_restores_original_files(tmp_path, monkeypatch):
    from pathlib import Path

    for name in ("boss_catalog.json", "profiles.json"):
        JsonStore(tmp_path / name).write({"name": name})
    original_replace = Path.replace

    def fail_profiles(source, target):
        if source.name == "profiles.json":
            raise PermissionError("文件占用")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_profiles)
    with pytest.raises(StorageError):
        clear_local_config(tmp_path)
    assert JsonStore(tmp_path / "boss_catalog.json").read() == {"name": "boss_catalog.json"}
    assert (tmp_path / "profiles.json").exists()


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


@pytest.mark.parametrize(("configured", "expected"), [
    (True, True),
    (False, False),
    (None, True),
    ("false", True),
])
def test_window_topmost_uses_project_seed_config(tmp_path, configured, expected):
    payload = {"timers": [{"name": "测试", "sec": 10}]}
    if configured is not None:
        payload["topmost"] = configured
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps(payload), encoding="utf-8")
    repository = BossRepository(tmp_path / "local.json", seed)
    assert repository.window_topmost() is expected

    # 即使本地目录数据保存过旧值，启动参数仍以项目配置为准。
    JsonStore(repository.store.path).write({"topmost": not expected, "timers": payload["timers"]})
    assert repository.window_topmost() is expected


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
    same_name = service.save("另一条路线", updated.timers)
    assert same_name.id != copy.id
    assert repo.load() == [updated, copy, same_name]
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
