import os
import sys

# Where the code is. In the Windows build, that is the folder PyInstaller unpacked the program into.
BASE_DIR = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))


def user_dir(kind):
    # The player's own folder for "config" or "state" files, in the usual place for the platform
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif kind == "config":
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    else:
        base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    path = os.path.join(base, "nightride")
    os.makedirs(path, exist_ok=True)
    return path


# Settings and the log are kept per user, so the player can be installed as a command
SETTINGS_FILE = os.path.join(user_dir("config"), "settings.ini")
LOG_FILE = os.path.join(user_dir("state"), "radio.log")
# Recently played songs, kept across restarts
HISTORY_FILE = os.path.join(user_dir("state"), "history.json")
# The settings that come with the code. A new user's settings start as a copy of these.
DEFAULT_SETTINGS_FILE = os.path.join(BASE_DIR, "settings.ini")
# The user manual, for Help > User manual: next to the code when running from source, next to
# nightride.exe in the Windows build, or in the share folder of the environment it was installed in
# with uv or pip. None if it can't be found.
MANUAL_NAME = "MANUAL.txt"
# The manual online, for when the file isn't there
MANUAL_URL = "https://github.com/matiasraisanen/nightride/blob/main/MANUAL.txt"


def find_manual():
    places = [BASE_DIR, os.path.join(sys.prefix, "share", "nightride")]
    if getattr(sys, "frozen", False):
        places.insert(0, os.path.dirname(sys.executable))
    for place in places:
        path = os.path.join(place, MANUAL_NAME)
        if os.path.isfile(path):
            return path
    return None


# The Windows build comes with its own copy of VLC, so VLC doesn't need to be installed.
# None when running from source: then the installed VLC is used.
VLC_DIR = os.path.join(BASE_DIR, "vlc")
if not os.path.isfile(os.path.join(VLC_DIR, "libvlc.dll")):
    VLC_DIR = None
