from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any


class StorageError(Exception):
    """可直接展示给用户的文件读写错误。"""


class JsonStore:
    def __init__(self, path: Path):
        self.path = path

    def read(self, default: Any = None) -> Any:
        if not self.path.exists():
            return default
        try:
            with self.path.open(encoding="utf-8-sig") as stream:
                return json.load(stream)
        except (OSError, ValueError) as exc:
            raise StorageError(
                f"无法读取配置：{self.path}\n{exc}\n"
                "请检查文件；同目录中的 .bak 文件保留了上一次保存内容。"
            ) from exc

    def write(self, payload: Any) -> None:
        """同盘临时文件写完后原子替换；失败时原配置保持完整。"""
        temp_path: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", suffix=".tmp",
                prefix=self.path.stem + "-", dir=self.path.parent, delete=False,
            ) as stream:
                temp_path = Path(stream.name)
                json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            if self.path.exists():
                shutil.copy2(self.path, self.path.with_suffix(self.path.suffix + ".bak"))
            os.replace(temp_path, self.path)
        except (OSError, ValueError, TypeError) as exc:
            raise StorageError(f"无法保存配置：{self.path}\n{exc}") from exc
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
