from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


def name_key(name: str) -> str:
    """规范化名称，忽略首尾空白和英文大小写。"""
    return name.strip().casefold()


def boss_key(boss) -> tuple[str, str, str]:
    """仅同一分组、地图内的同名怪物共享计时唯一约束。"""
    return boss.group, boss.map, name_key(boss.name)


@dataclass(frozen=True)
class BossDefinition:
    id: str
    group: str
    map: str
    name: str
    sec: int
    tip: str
    armed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TimerState(StrEnum):
    RUNNING = "running"
    PAUSED = "paused"
    EXPIRED = "expired"


@dataclass
class TimerEntry:
    id: str
    boss_id: str
    group: str
    map: str
    name: str
    sec: int
    tip: str
    deadline: float | None
    paused_remaining: float | None = None
    selected: bool = True

    def state(self, now: float) -> TimerState:
        if self.paused_remaining is not None:
            return TimerState.PAUSED
        if self.deadline is not None and self.deadline <= now:
            return TimerState.EXPIRED
        return TimerState.RUNNING

    def remaining(self, now: float) -> float:
        if self.paused_remaining is not None:
            return self.paused_remaining
        return max(0.0, (self.deadline or now) - now)

    def display_seconds(self, now: float) -> int:
        # 向上取整，防止尚未到期却提前显示 00:00。
        return math.ceil(self.remaining(now))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Profile:
    id: str
    name: str
    created_at: float
    updated_at: float
    timers: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
