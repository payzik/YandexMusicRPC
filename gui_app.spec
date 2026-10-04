# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules('winrt.windows.media.control')
# Phone mode (Ynison): websockets and the protobuf stack are imported lazily at runtime.
for _pkg in ('yandex_music.ynison', 'websockets', 'betterproto', 'grpclib'):
    hiddenimports += collect_submodules(_pkg)

analysis = Analysis(
    ['gui_app.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets')],
    hiddenimports=hiddenimports + [
        'winrt.windows.foundation.collections',
        'winrt.windows.foundation',
        'winrt.windows.storage.streams',
        'winrt.windows.media',
    ],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz, analysis.scripts, [], name='WinYandexMusicRPC',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False, argv_emulation=False,
    icon=['assets/YMRPC_ico.ico'],
)
coll = COLLECT(exe, analysis.binaries, analysis.zipfiles, analysis.datas,
    name='WinYandexMusicRPC', strip=False, upx=False)
