"""供源码启动及 Windows 打包共用的入口。"""
import sys
from pathlib import Path

# 源码入口根据自身位置定位 src，避免移动项目后依赖旧的可编辑安装路径。
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from boss_timer.app import main

if __name__ == "__main__":
    raise SystemExit(main())
