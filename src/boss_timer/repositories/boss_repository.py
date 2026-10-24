from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from boss_timer.domain.models import BossDefinition
from boss_timer.repositories.json_store import JsonStore, StorageError


class BossRepository:
    def __init__(self, path: Path, seed_path: Path):
        self.store = JsonStore(path)
        self.seed_path = seed_path
        self.metadata: dict = {}

    def load(self) -> list[BossDefinition]:
        source = self.store if self.store.path.exists() else JsonStore(self.seed_path)
        payload = source.read()
        if not isinstance(payload, dict) or not isinstance(payload.get("timers"), list):
            raise StorageError("BOSS 配置格式错误：缺少 timers 列表。")
        self.metadata = {key: value for key, value in payload.items() if key != "timers"}
        bosses = []
        used_ids: set[str] = set()
        for index, item in enumerate(payload["timers"]):
            if not isinstance(item, dict) or not str(item.get("name", "")).strip():
                raise StorageError(f"第 {index + 1} 条 BOSS 配置缺少名称。")
            try:
                seconds = int(item.get("sec") or 0)
            except (ValueError, TypeError):
                seconds = 0
            group = str(item.get("group") or "").strip()
            map_name = str(item.get("map") or "").strip()
            name = str(item["name"]).strip()
            # 为旧配置分配可复现的 ID，改名后 ID 也不会改变。
            boss_id = str(item.get("id") or uuid5(
                NAMESPACE_URL, f"legend-boss:{index}:{group}:{map_name}:{name}"
            ))
            if boss_id in used_ids:
                raise StorageError(f"BOSS 配置存在重复 ID：{boss_id}")
            used_ids.add(boss_id)
            bosses.append(BossDefinition(
                boss_id, group, map_name, name, max(0, seconds),
                str(item.get("tip") or name), bool(item.get("armed", True)),
            ))
        return bosses

    def save(self, bosses: list[BossDefinition]) -> None:
        # 保留导入文件的其他顶层字段，旧识别关键词不参与新工具。
        self.store.write({**self.metadata, "version": 3,
                          "timers": [boss.to_dict() for boss in bosses]})

    def save_checked(self, bosses: list[BossDefinition], ids: set[str]) -> list[BossDefinition]:
        updated = [replace(boss, armed=boss.id in ids) for boss in bosses]
        self.save(updated)
        return updated
