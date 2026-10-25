from __future__ import annotations

import math
import time
from dataclasses import replace
from datetime import datetime
from typing import Callable
from uuid import uuid4

from boss_timer.domain.models import BossDefinition, TimerEntry, TimerState, name_key


class TimerError(ValueError):
    pass


class DuplicateBossError(TimerError):
    def __init__(self, entry: TimerEntry):
        super().__init__(f"“{entry.name}”已在“{entry.map or entry.group}”计时，不能重复添加。")
        self.entry_id = entry.id


class TimerService:
    """以绝对时间为准；统一时钟便于验证休眠、暂停及到期边界。"""

    CLEANUP_SECONDS = 120

    def __init__(self, clock: Callable[[], float] = time.time):
        self.clock = clock
        self.entries: dict[str, TimerEntry] = {}

    def start(self, boss: BossDefinition) -> TimerEntry:
        if boss.sec <= 0:
            raise TimerError("请先双击该 BOSS，设置大于 0 的刷新时间。")
        for entry in self.entries.values():
            if name_key(entry.name) == name_key(boss.name):
                raise DuplicateBossError(entry)
        entry = TimerEntry(
            str(uuid4()), boss.id, boss.group, boss.map, boss.name,
            boss.sec, boss.tip, self.clock() + boss.sec,
        )
        self.entries[entry.id] = entry
        return entry

    def pause(self, entry_id: str) -> bool:
        entry = self.entries[entry_id]
        now = self.clock()
        if entry.state(now) != TimerState.RUNNING:
            return False
        entry.paused_remaining = entry.remaining(now)
        entry.deadline = None
        return True

    def resume(self, entry_id: str) -> bool:
        entry = self.entries[entry_id]
        if entry.paused_remaining is None:
            return False
        entry.deadline = self.clock() + entry.paused_remaining
        entry.paused_remaining = None
        return True

    def restart(self, entry_id: str) -> bool:
        """保留原条目 ID，从完整刷新间隔重新开始，适用于所有计时状态。"""
        entry = self.entries.get(entry_id)
        if entry is None:
            return False
        if entry.sec <= 0:
            raise TimerError("请先设置大于 0 的刷新时间。")
        entry.deadline = self.clock() + entry.sec
        entry.paused_remaining = None
        return True

    def pause_all(self) -> int:
        return sum(self.pause(entry_id) for entry_id in self.entries)

    def start_all(self) -> int:
        """仅恢复当前列表内的暂停计时，不新增或重置项目。"""
        return sum(self.resume(entry_id) for entry_id in self.entries)

    def remove(self, entry_id: str) -> None:
        self.entries.pop(entry_id, None)

    def cleanup(self) -> list[str]:
        now = self.clock()
        expired = [entry.id for entry in self.entries.values()
                   if entry.paused_remaining is None and entry.deadline is not None
                   and now >= entry.deadline + self.CLEANUP_SECONDS]
        for entry_id in expired:
            self.remove(entry_id)
        return expired

    def sorted_entries(self) -> list[TimerEntry]:
        now = self.clock()
        # dict 的插入顺序配合稳定排序，避免同秒条目来回跳动。
        return sorted(self.entries.values(), key=lambda entry: entry.remaining(now))

    def validate_edit(self, boss: BossDefinition) -> None:
        own_entries = [e for e in self.entries.values() if e.boss_id == boss.id]
        if own_entries:
            for entry in self.entries.values():
                if entry.boss_id != boss.id and name_key(entry.name) == name_key(boss.name):
                    raise TimerError("修改后的名称与右侧已有怪物重名，请先删除对应计时。")

    def sync_definition(self, boss: BossDefinition) -> None:
        self.validate_edit(boss)
        for entry in self.entries.values():
            if entry.boss_id == boss.id:
                entry.name, entry.tip, entry.sec = boss.name, boss.tip, boss.sec

    def snapshot(self) -> list[dict]:
        # 右侧列表中的项目均为有效计时，保存方案时全部写入。
        return [entry.to_dict() for entry in self.sorted_entries()]

    def load_fresh(self, payload: list[dict], definitions: list[BossDefinition]) -> None:
        """按名单匹配当前资料，验证完成后统一从完整时长开始。"""
        staged = TimerService(self.clock)
        now = self.clock()
        staged.clock = lambda: now
        problems = []
        for raw in payload:
            if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
                problems.append("配置中的怪物名称格式无效")
                continue
            name = raw["name"]
            matches = [boss for boss in definitions
                       if name_key(boss.name) == name_key(name)
                       and boss.map == raw.get("map", "")
                       and boss.group == raw.get("group", "")]
            location = " / ".join(filter(None, [raw.get("group"), raw.get("map"), name]))
            if len(matches) != 1:
                problems.append(f"{location}：未找到唯一匹配的 BOSS 资料")
                continue
            try:
                staged.start(matches[0])
            except TimerError as exc:
                problems.append(f"{location}：{exc}")
        if problems:
            raise TimerError("无法加载该配置，当前列表已保留：\n" + "\n".join(problems))
        self.entries = staged.entries

    def restore(self, payload: list[dict], definitions: list[BossDefinition]) -> int:
        """先完整验证再替换，损坏的方案不会清空当前列表。

        运行条目保留绝对刷新时间；暂停条目保留冻结的剩余秒数。
        左侧资料可能在保存方案后改名，因此用稳定 boss_id 同步最新定义。
        """
        definitions_by_id = {boss.id: boss for boss in definitions}
        staged: dict[str, TimerEntry] = {}
        seen_names: set[str] = set()
        now = self.clock()
        removed = 0
        try:
            for raw in payload:
                entry = TimerEntry(**raw)
                if entry.boss_id in definitions_by_id:
                    boss = definitions_by_id[entry.boss_id]
                    entry = replace(entry, group=boss.group, map=boss.map, name=boss.name,
                                    sec=boss.sec, tip=boss.tip)
                if not all(isinstance(v, str) for v in (entry.id, entry.boss_id, entry.name,
                                                        entry.map, entry.group, entry.tip)):
                    raise ValueError("计时条目的文本格式错误")
                if not entry.id or not entry.name.strip() or entry.sec <= 0:
                    raise ValueError("计时条目缺少有效名称、ID 或刷新时间")
                if not all(isinstance(v, (float, int)) and math.isfinite(v)
                           for v in [entry.sec]):
                    raise ValueError("刷新时间格式错误")
                if entry.paused_remaining is not None:
                    if not math.isfinite(entry.paused_remaining) or entry.paused_remaining <= 0:
                        raise ValueError("暂停剩余时间无效")
                    entry.deadline = None
                elif entry.deadline is None or not math.isfinite(entry.deadline):
                    raise ValueError("刷新时间无效")
                else:
                    # 确保时间能由系统转换为表格中的日期，拒绝异常的大数。
                    datetime.fromtimestamp(entry.deadline)
                    if now >= entry.deadline + self.CLEANUP_SECONDS:
                        removed += 1
                        continue
                key = name_key(entry.name)
                if entry.id in staged or key in seen_names:
                    raise ValueError("方案中存在重复怪物名称或计时 ID")
                entry.selected = True
                staged[entry.id] = entry
                seen_names.add(key)
        except (ValueError, TypeError, AttributeError, OverflowError, OSError) as exc:
            raise TimerError(f"无法加载该方案：{exc}") from exc
        self.entries = staged
        return removed
