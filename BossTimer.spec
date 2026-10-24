# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

root = Path(SPECPATH)
a = Analysis(
    [str(root / 'run.py')],
    pathex=[str(root / 'src')],
    binaries=[],
    datas=[(str(root / 'src/boss_timer/resources/boss_config.json'), 'boss_timer/resources'),
           (str(root / 'src/boss_timer/resources/icons'), 'boss_timer/resources/icons')],
    hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtQml',
              'PySide6.QtQuick', 'PySide6.QtPdf'],
    noarchive=False,
)
# Qt 6.12 使用 Windows 自带的 ICU。构建环境 PATH 中的 Poppler 也有
# 同名 icuuc.dll，但它的导出符号带版本后缀，与 Qt 不兼容。禁止把它
# 收入发布包，让加载器使用系统组件；不需要更改用户的系统或环境变量。
a.binaries = [entry for entry in a.binaries
              if Path(entry[0]).name.lower() not in {'icuuc.dll', 'icudt78.dll'}]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='BossTimer', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False, disable_windowed_traceback=False,
)
