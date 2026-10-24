from __future__ import annotations

from pathlib import Path
import math
from datetime import datetime

from boss_timer.domain.models import Profile
from boss_timer.repositories.json_store import JsonStore, StorageError


class ProfileRepository:
    def __init__(self, path: Path):
        self.store = JsonStore(path)

    def load(self) -> list[Profile]:
        payload = self.store.read({"version": 1, "profiles": []})
        try:
            profiles = [Profile(**item) for item in payload["profiles"]]
            if len({p.id for p in profiles}) != len(profiles):
                raise ValueError("存在重复的方案 ID")
            for profile in profiles:
                if not profile.id or not profile.name.strip() or not isinstance(profile.timers, list):
                    raise ValueError("方案缺少 ID、名称或计时列表")
                for timestamp in (profile.created_at, profile.updated_at):
                    if not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp):
                        raise ValueError("方案时间格式错误")
                    datetime.fromtimestamp(timestamp)
            return profiles
        except (KeyError, TypeError, AttributeError, ValueError, OverflowError, OSError) as exc:
            raise StorageError(f"计时方案格式错误：{exc}") from exc

    def save(self, profiles: list[Profile]) -> None:
        self.store.write({"version": 1, "profiles": [p.to_dict() for p in profiles]})
