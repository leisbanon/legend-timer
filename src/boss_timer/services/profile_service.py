from __future__ import annotations

import time
from typing import Callable
from uuid import uuid4

from boss_timer.domain.models import Profile
from boss_timer.repositories.profile_repository import ProfileRepository


class ProfileService:
    def __init__(self, repository: ProfileRepository, clock: Callable[[], float] = time.time):
        self.repository = repository
        self.clock = clock
        self.profiles = repository.load()

    def find(self, profile_id: str | None) -> Profile | None:
        return next((p for p in self.profiles if p.id == profile_id), None)

    def delete(self, profile_id: str) -> None:
        updated = [p for p in self.profiles if p.id != profile_id]
        self.repository.save(updated)
        self.profiles = updated

    def save(self, name: str, timers: list[dict], profile_id: str | None = None) -> Profile:
        name = name.strip()
        if not name:
            raise ValueError("请输入配置名称。")
        if len(name) > 80:
            raise ValueError("配置名称不能超过 80 个字符。")
        if not timers:
            raise ValueError("请至少勾选一条计时后保存。")
        if profile_id is not None and self.find(profile_id) is None:
            raise ValueError("原配置不存在，请另存为新配置。")
        now = self.clock()
        previous = self.find(profile_id)
        profile = Profile(previous.id if previous else str(uuid4()), name,
                          previous.created_at if previous else now, now, timers)
        updated = [profile if p.id == profile.id else p for p in self.profiles]
        if previous is None:
            updated.append(profile)
        # 只有磁盘写入成功才提交内存，避免失败后显示“已保存”。
        self.repository.save(updated)
        self.profiles = updated
        return profile
