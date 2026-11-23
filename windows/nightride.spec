# PyInstaller recipe for the Windows build. Run through build.ps1, which first fetches VLC.
import os

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.dirname(SPECPATH)

a = Analysis(
    [os.path.join(ROOT, "radio.py")],
    pathex=[ROOT],
    datas=[
        (os.path.join(ROOT, "settings.ini"), "."),
        # The VLC libraries and plugins, prepared by build.ps1. Copied as plain files: they are
        # loaded by VLC itself, so PyInstaller shouldn't analyse them.
        (os.path.join(ROOT, "build", "vlc"), "vlc"),
    ],
    # blessed picks its terminal description from jinxed at run time, by name
    hiddenimports=collect_submodules("jinxed"),
    excludes=["tkinter"],
)
# PyInstaller also finds a VLC installed on the build machine through python-vlc. Leave it out:
# the program uses its own copy from build\vlc.
a.binaries = [b for b in a.binaries if not os.path.basename(b[0]).lower().startswith("libvlc")]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="nightride",
    console=True,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="nightride", upx=False)
