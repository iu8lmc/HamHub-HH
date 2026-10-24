# PyInstaller: pyinstaller HH.spec   ->  dist/HH.exe (Windows), dist/HH (Linux), dist/HH.app (macOS)
import sys

IS_MAC = sys.platform == 'darwin'
IS_WIN = sys.platform.startswith('win')

hidden = []
if IS_WIN:
    hidden += ['pystray._win32']
elif IS_MAC:
    hidden += ['pystray._darwin']
else:
    hidden += ['pystray._xorg', 'pystray._appindicator', 'pystray._gtk', 'pystray._util.gtk', 'pystray._util.notify_dbus']

a = Analysis(['HH.py'], pathex=[], binaries=[], datas=[('hh.ico', '.')], hiddenimports=hidden, hookspath=[], runtime_hooks=[], excludes=[])
pyz = PYZ(a.pure)

if IS_MAC:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='HH', console=False, icon='hh.icns')
    coll = COLLECT(exe, a.binaries, a.datas, name='HH')
    app = BUNDLE(coll, name='HH.app', icon='hh.icns', bundle_identifier='cloud.hamhub.hh',
                 info_plist={'CFBundleName': 'HH', 'CFBundleDisplayName': 'HH - HamHub Log', 'CFBundleShortVersionString': '1.2.0',
                             'LSUIElement': True,  # niente icona nel Dock: HH vive nella barra dei menu
                             'NSHighResolutionCapable': True})
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='HH', console=not IS_WIN, icon='hh.ico' if IS_WIN else None, upx=False)
