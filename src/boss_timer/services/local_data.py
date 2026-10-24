"""本地配置迁移和恢复默认；只处理程序自己的配置文件。"""

from pathlib import Path
import shutil
import tempfile

from boss_timer.repositories.json_store import StorageError


CONFIG_NAMES = ("boss_catalog.json", "profiles.json", "settings.json")


def config_files(directory: Path) -> list[Path]:
    files = []
    for name in CONFIG_NAMES:
        for suffix in ("", ".bak"):
            path = directory / (name + suffix)
            if path.is_file():
                files.append(path)
        # JsonStore 中断写入可能留下的临时文件，不触及其他文件。
        files.extend(directory.glob(f"{Path(name).stem}-*.tmp"))
    return files


def migrate_local_data(directory: Path, legacy_directory: Path) -> None:
    """逐文件迁移缺失项，目标已有的数据优先；保留旧文件供回退。"""
    directory.mkdir(parents=True, exist_ok=True)
    for source in config_files(legacy_directory):
        if source.suffix == ".tmp":
            continue
        target = directory / source.name
        if target.exists():
            continue
        # 先复制到临时文件再替换，复制中断不会生成不完整的正式配置。
        with tempfile.NamedTemporaryFile(dir=directory, prefix="migration-", delete=False) as stream:
            temporary = Path(stream.name)
        try:
            shutil.copy2(source, temporary)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)


def clear_local_config(directory: Path, legacy_directory: Path | None = None) -> None:
    """清除新旧目录配置及备份；移动失败时回滚，保留日志和进程锁。"""
    directories = [directory]
    if legacy_directory is not None and legacy_directory != directory:
        directories.append(legacy_directory)
    moved = []
    staging = Path(tempfile.mkdtemp(prefix="reset-", dir=directory))
    try:
        for location in directories:
            for source in config_files(location):
                target = staging / str(len(moved))
                source.replace(target)
                moved.append((source, target))
    except OSError as exc:
        try:
            for source, target in reversed(moved):
                target.replace(source)
        except OSError as rollback_error:
            # 回滚也失败时保留暂存目录，不能清除仍待恢复的原文件。
            raise StorageError(f"恢复失败，部分原文件保留在 {staging}：{rollback_error}") from exc
        staging.rmdir()
        raise StorageError(f"无法恢复默认配置：{exc}") from exc
    # 所有文件均已成功移出配置路径，清理的范围仅限此次创建的暂存目录。
    shutil.rmtree(staging)
