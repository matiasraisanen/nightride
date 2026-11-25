import argparse
import base64
import logging
import os
import shutil
import subprocess
import sys
import time
import traceback
import urllib.parse
import webbrowser

import blessed

import settings
from logger import Logger
from paths import LOG_FILE, MANUAL_URL, find_manual
from screen import Screen, clip, text_width

from level_meter import CEILING_DB, FLOOR_DB, LevelMeter
from nightride_api import NightRideAPI, jingle_title, song_kind

# Colours by name. The first 16 are the VGA text mode palette. Terminals with true colour show these
# exactly. On others, blessed picks the closest colour they have.
COLORS = {
    "black": "#000000",
    "blue": "#0000aa",
    "green": "#00aa00",
    "cyan": "#00aaaa",
    "red": "#aa0000",
    "magenta": "#aa00aa",
    "lightgray": "#aaaaaa",
    "darkgray": "#555555",
    "lightblue": "#5555ff",
    "lightgreen": "#55ff55",
    "lightcyan": "#55ffff",
    "lightred": "#ff5555",
    "lightmagenta": "#ff55ff",
    "yellow": "#ffff55",
    "white": "#ffffff",
    # Not in the VGA palette, for the other themes
    "purple": "#5f0087",
    "darkpurple": "#5f005f",
    "charcoal": "#303030",
    "darkcharcoal": "#262626",
    "nearblack": "#121212",
    "slate": "#444444",
    "gray": "#8a8a8a",
    "pale": "#d0d0d0",
    "navy": "#00005f",
    "orange": "#ff8700",
    "hotpink": "#ff0087",
    "pink": "#ff5faf",
    "lightpink": "#ff87ff",
    "brightred": "#ff0000",
    "blood": "#d70000",
    "darkred": "#870000",
    "deepred": "#5f0000",
    "amberbright": "#ffd700",
    "amber": "#ffaf00",
    "amberdim": "#d78700",
    "amberdark": "#875f00",
    "greenbright": "#87ff87",
    "greendark": "#005f00",
    # The Commodore 64's blues, from the Colodore palette. Its light blue is too dim for text on the
    # dark blue, so text uses a brighter one.
    "c64dark": "#2e2c9b",
    "c64border": "#706deb",
    "c64light": "#a5a2f7",
    "c64mid": "#4a47c2",
}


def rgb(color):
    # "#rrggbb" => (r, g, b)
    return tuple(int(color[i : i + 2], 16) for i in (1, 3, 5))


# Style name => (foreground, background), per theme. A third value "underline" underlines the text.
# Hotkeys (menu_hot, menu_sel_hot) are underlined in every theme, so they show even where their colour
# is close to the text around them.
# Unlit VU meter segments are grey in most themes. Some terminals brighten colours that are too dark to
# read, and a dark shade of the lit colour would then look just like the lit segments.
DOS_THEME = {
    "desktop": ("lightgray", "blue"),
    "menu": ("black", "lightgray"),
    "menu_hot": ("red", "lightgray", "underline"),
    "menu_sel": ("black", "green"),
    "menu_sel_hot": ("red", "green", "underline"),
    "window": ("lightgray", "blue"),
    "window_border": ("white", "blue"),
    "window_title": ("yellow", "blue"),
    "label": ("cyan", "blue"),
    "value": ("white", "blue"),
    "artist": ("white", "blue"),
    "song": ("white", "blue"),
    "number": ("yellow", "blue"),
    "bar_full": ("lightcyan", "blue"),
    "bar_empty": ("cyan", "blue"),
    "vu_low": ("lightgreen", "blue"),
    "vu_mid": ("yellow", "blue"),
    "vu_high": ("lightred", "blue"),
    "vu_off": ("lightblue", "blue"),
    "error": ("white", "red"),
    "warning": ("black", "yellow"),
    "dialog": ("black", "lightgray"),
    "dialog_border": ("white", "lightgray"),
    "dialog_value": ("blue", "lightgray"),
    "dialog_key": ("red", "lightgray"),
    "list": ("black", "cyan"),
    "list_sel": ("white", "blue"),
    "button": ("black", "green"),
    # Scroll bars: arrows and the thumb
    "scrollbar": ("white", "blue"),
    "button_focus": ("white", "green"),
    "button_cancel": ("lightgray", "red"),
    "button_cancel_focus": ("white", "red"),
    "button_shadow": ("black", "lightgray"),
    "shadow": ("darkgray", "black"),
}

# Purple and cyan on dark grey, like the original player. Anything not listed comes from the DOS theme.
SYNTHWAVE_THEME = {
    **DOS_THEME,
    "desktop": ("darkpurple", "darkcharcoal"),
    "menu": ("black", "cyan"),
    "menu_hot": ("purple", "cyan", "underline"),
    "menu_sel": ("white", "magenta"),
    "menu_sel_hot": ("lightcyan", "magenta", "underline"),
    "window": ("lightgray", "charcoal"),
    "window_border": ("white", "charcoal"),
    "window_title": ("lightcyan", "charcoal"),
    "label": ("lightmagenta", "charcoal"),
    "value": ("white", "charcoal"),
    "artist": ("black", "cyan"),
    "song": ("lightcyan", "purple"),
    "number": ("lightcyan", "charcoal"),
    "bar_full": ("lightmagenta", "charcoal"),
    "bar_empty": ("magenta", "charcoal"),
    "vu_low": ("lightcyan", "charcoal"),
    "vu_mid": ("lightmagenta", "charcoal"),
    "vu_high": ("lightred", "charcoal"),
    "vu_off": ("slate", "charcoal"),
    "warning": ("black", "lightmagenta"),
    "dialog": ("white", "purple"),
    "dialog_border": ("lightcyan", "purple"),
    "dialog_value": ("lightcyan", "purple"),
    "dialog_key": ("lightmagenta", "purple"),
    "list": ("black", "cyan"),
    "list_sel": ("white", "magenta"),
    "button": ("black", "cyan"),
    "scrollbar": ("black", "cyan"),
    "button_focus": ("black", "lightcyan"),
    "button_cancel": ("white", "magenta"),
    "button_cancel_focus": ("black", "lightmagenta"),
    "button_shadow": ("black", "purple"),
}

# Neon pink, orange and yellow on navy, like a sunset over the highway
OUTRUN_THEME = {
    **DOS_THEME,
    "desktop": ("purple", "black"),
    "menu": ("black", "orange"),
    "menu_hot": ("purple", "orange", "underline"),
    "menu_sel": ("white", "hotpink"),
    "menu_sel_hot": ("yellow", "hotpink", "underline"),
    "window": ("pale", "navy"),
    "window_border": ("pink", "navy"),
    "window_title": ("yellow", "navy"),
    "label": ("pink", "navy"),
    "value": ("white", "navy"),
    "artist": ("black", "orange"),
    "song": ("white", "hotpink"),
    "number": ("yellow", "navy"),
    "bar_full": ("orange", "navy"),
    "bar_empty": ("darkpurple", "navy"),
    "vu_low": ("yellow", "navy"),
    "vu_mid": ("orange", "navy"),
    "vu_high": ("hotpink", "navy"),
    "vu_off": ("slate", "navy"),
    "dialog": ("white", "darkpurple"),
    "dialog_border": ("pink", "darkpurple"),
    "dialog_value": ("orange", "darkpurple"),
    "dialog_key": ("yellow", "darkpurple"),
    "list": ("black", "orange"),
    "list_sel": ("white", "hotpink"),
    "button": ("black", "orange"),
    "scrollbar": ("black", "orange"),
    "button_focus": ("black", "yellow"),
    "button_cancel": ("white", "hotpink"),
    "button_cancel_focus": ("black", "lightpink"),
    "button_shadow": ("black", "darkpurple"),
}

# Blood red and grey on black, for the darker stations
DARKSYNTH_THEME = {
    **DOS_THEME,
    "desktop": ("deepred", "black"),
    "menu": ("lightgray", "slate"),
    "menu_hot": ("brightred", "slate", "underline"),
    "menu_sel": ("white", "blood"),
    "menu_sel_hot": ("black", "blood", "underline"),
    "window": ("lightgray", "nearblack"),
    "window_border": ("blood", "nearblack"),
    "window_title": ("brightred", "nearblack"),
    "label": ("gray", "nearblack"),
    "value": ("pale", "nearblack"),
    "artist": ("white", "darkred"),
    "song": ("pale", "deepred"),
    "number": ("brightred", "nearblack"),
    "bar_full": ("blood", "nearblack"),
    "bar_empty": ("deepred", "nearblack"),
    "vu_low": ("blood", "nearblack"),
    "vu_mid": ("brightred", "nearblack"),
    "vu_high": ("lightred", "nearblack"),
    "vu_off": ("slate", "nearblack"),
    "error": ("white", "blood"),
    "warning": ("black", "lightgray"),
    "dialog": ("pale", "charcoal"),
    "dialog_border": ("blood", "charcoal"),
    "dialog_value": ("white", "charcoal"),
    "dialog_key": ("brightred", "charcoal"),
    "list": ("pale", "slate"),
    "list_sel": ("white", "darkred"),
    "button": ("white", "darkred"),
    "scrollbar": ("white", "darkred"),
    "button_focus": ("white", "blood"),
    "button_cancel": ("pale", "slate"),
    "button_cancel_focus": ("black", "lightgray"),
    "button_shadow": ("black", "charcoal"),
}

# Light blue on dark blue inside a light blue border, like the Commodore 64 start screen
C64_THEME = {
    **DOS_THEME,
    "desktop": ("c64border", "c64border"),
    "menu": ("white", "c64border"),
    "menu_hot": ("white", "c64border", "underline"),
    "menu_sel": ("c64light", "c64dark"),
    "menu_sel_hot": ("white", "c64dark", "underline"),
    "window": ("c64light", "c64dark"),
    "window_border": ("c64light", "c64dark"),
    "window_title": ("white", "c64dark"),
    "label": ("c64light", "c64dark"),
    "value": ("white", "c64dark"),
    "artist": ("c64dark", "c64light"),
    "song": ("c64dark", "c64light"),
    "number": ("white", "c64dark"),
    "bar_full": ("c64light", "c64dark"),
    "bar_empty": ("c64mid", "c64dark"),
    "vu_low": ("lightgreen", "c64dark"),
    "vu_mid": ("yellow", "c64dark"),
    "vu_high": ("lightred", "c64dark"),
    "vu_off": ("c64mid", "c64dark"),
    "dialog": ("c64dark", "c64light"),
    "dialog_border": ("white", "c64light"),
    "dialog_value": ("white", "c64light"),
    "dialog_key": ("white", "c64light"),
    "list": ("c64light", "c64dark"),
    "list_sel": ("c64dark", "white"),
    "button": ("c64light", "c64dark"),
    "scrollbar": ("c64light", "c64dark"),
    "button_focus": ("white", "c64dark"),
    "button_cancel": ("white", "red"),
    "button_cancel_focus": ("yellow", "red"),
    "button_shadow": ("c64dark", "c64light"),
}


def crt_theme(brightest, bright, dim, dark):
    # A single-colour monitor: one colour in four brightnesses on black, highlights as inverted blocks
    return {
        **DOS_THEME,
        "desktop": (dark, "nearblack"),
        "menu": ("nearblack", bright),
        # With only one colour, hotkeys are told apart by underlining
        "menu_hot": ("nearblack", bright, "underline"),
        "menu_sel": (bright, dark),
        "menu_sel_hot": (brightest, dark, "underline"),
        "window": (dim, "nearblack"),
        "window_border": (bright, "nearblack"),
        "window_title": (brightest, "nearblack"),
        "label": (dim, "nearblack"),
        "value": (bright, "nearblack"),
        "artist": ("nearblack", bright),
        "song": ("nearblack", dim),
        "number": (brightest, "nearblack"),
        "bar_full": (bright, "nearblack"),
        "bar_empty": (dark, "nearblack"),
        "vu_low": (dim, "nearblack"),
        "vu_mid": (bright, "nearblack"),
        "vu_high": (brightest, "nearblack"),
        "vu_off": ("slate", "nearblack"),
        "error": ("nearblack", brightest),
        "warning": ("nearblack", bright),
        "dialog": (bright, dark),
        "dialog_border": (brightest, dark),
        "dialog_value": (brightest, dark),
        "dialog_key": (brightest, dark),
        "list": ("nearblack", dim),
        "list_sel": ("nearblack", brightest),
        "button": ("nearblack", bright),
        "scrollbar": ("nearblack", bright),
        "button_focus": ("nearblack", brightest),
        "button_cancel": (bright, "nearblack"),
        "button_cancel_focus": (brightest, "nearblack"),
        "button_shadow": ("nearblack", dark),
        "shadow": ("nearblack", "black"),
    }


# In the order they appear in the menus
THEMES = {
    "Synthwave": SYNTHWAVE_THEME,
    "Outrun": OUTRUN_THEME,
    "Darksynth": DARKSYNTH_THEME,
    "DOS": DOS_THEME,
    "C64": C64_THEME,
    "Amber CRT": crt_theme("amberbright", "amber", "amberdim", "amberdark"),
    "Green CRT": crt_theme("greenbright", "lightgreen", "green", "greendark"),
}

# Labels next to the song for jingles and live shows. In the menu bar's colors, which stand out
# from the main window in every theme.
for _theme in THEMES.values():
    _theme.setdefault("badge", _theme["menu"])

# Theme menu hotkeys, where the first letter is already taken
THEME_HOTKEYS = {"Darksynth": "k"}

# Key hints on the bottom status line, per screen
STATUS_HINTS = {
    "main": [
        ("F1", "Help"),
        ("F2", "Stations"),
        ("F10", "Menu"),
        ("←→", "Station"),
        ("↑↓", "Volume"),
        ("Alt-X", "Exit"),
    ],
    "menu": [("←→", "Menus"), ("↑↓", "Select"), ("Enter", "Choose"), ("Esc", "Close")],
    "stations": [("↑↓", "Station"), ("←→", "Button"), ("Enter", "Select"), ("Esc", "Cancel")],
    "history": [("↑↓", "Song"), ("←→", "Button"), ("Enter", "Select"), ("Esc", "Close")],
    "search": [("←→↑↓", "Move"), ("B S Y G", "Open site"), ("Enter", "Open"), ("Esc", "Cancel")],
    "about": [("Enter", "Close")],
    "stream_info": [("↑↓", "Scroll"), ("Enter", "Close")],
    "help": [("↑↓", "Scroll"), ("Enter", "Close")],
    "exit": [("←→", "Move"), ("Enter", "Select"), ("Y", "Yes"), ("N", "No"), ("Esc", "Cancel")],
    "settings": [("↑↓", "Move"), ("←→", "Change"), ("Tab", "Next"), ("Enter", "OK"), ("Esc", "Cancel")],
    # The same dialog, on a field that opens a picker
    "settings_picker": [("↑↓", "Move"), ("Enter", "Choose"), ("Tab", "Next"), ("Esc", "Cancel")],
    "notifications": [("↑↓", "Move"), ("Space", "Toggle"), ("Enter", "OK"), ("Esc", "Cancel")],
}

ENTER_KEYS = ("\n", "\r", "KEY_ENTER")
# Only these count as digits: str.isdigit() also accepts the likes of "²", which int() refuses
DIGITS = tuple("0123456789")

# Contents of the help dialog: (keys, description) rows, a heading (keys only), or None for a blank line
HELP = [
    ("Main screen", None),
    ("←→  1-7", "Change station"),
    ("↑↓", "Volume in steps of 10"),
    ("Shift-↑↓", "Volume in steps of 1"),
    ("M", "Mute"),
    ("F2", "Stations"),
    ("F3", "Recently played"),
    ("F", "Find this song"),
    ("V", "VU meter on/off"),
    ("C  D", "Clock, date on/off"),
    ("T  Shift-T", "Next, previous theme"),
    ("F10", "Menus, or Alt + red letter"),
    ("F1", "This help"),
    ("Esc", "Exit, asks first"),
    ("Alt-X  F12", "Exit right away"),
    None,
    ("Menus and dialogs", None),
    ("↑↓  ←→  Tab", "Move"),
    ("Enter", "Choose"),
    ("Esc", "Close or cancel"),
    None,
    ("Mouse", None),
    ("Click", "Menus, buttons, key hints"),
    ("Double-click", "Play or find in a list"),
    ("Wheel", "Volume, or scroll a list"),
    ("Click volume", "◄ ► step, bar sets level"),
    ("Click number", "Mute"),
    ("Click station", "Stations"),
    ("Click song", "Find this song"),
]

# Status line hints that do something when clicked: the hint's key => the key it sends
HINT_KEYS = {
    "F1": "KEY_F1",
    "F2": "KEY_F2",
    "F10": "KEY_F10",
    "Alt-X": "ALT_x",
    "Enter": "\n",
    "Esc": "KEY_ESCAPE",
    "Tab": "KEY_TAB",
    "Space": " ",
    "Y": "y",
    "N": "n",
}

# Mouse reporting: clicks (1000), sent in the SGR format (1006) that has no limit on the column
MOUSE_MODES = (1000, 1006)
# Two clicks on the same spot within this many seconds are a double-click
DOUBLE_CLICK_SECONDS = 0.4

AUTHOR_EMAIL = "matias@matiasraisanen.com"
REPOSITORY = "github.com/matiasraisanen/nightride"

# Focusable items in the settings dialog, top to bottom
(
    SETTINGS_START, SETTINGS_VOLUME, SETTINGS_CLOCK, SETTINGS_DATE, SETTINGS_SYNC, SETTINGS_NOTIFY,
    SETTINGS_OK, SETTINGS_CANCEL,
) = range(8)

# Messages above the status line that can be turned off: (kind, label in the picker, name in
# settings.ini)
NOTIFICATION_KINDS = [
    ("song", "New songs", "songs"),
    ("action", "Key actions", "actions"),
    ("error", "Errors", "errors"),
]
ALL_NOTIFICATIONS = {kind for kind, _, _ in NOTIFICATION_KINDS}

# Sites for Find this song: (name, setting with its search address, whether the station's name is
# added to the search).
# Bandcamp and YouTube look for every word, so only Google gets the station.
# Spotify opens the song itself when its Spotify ID is known, otherwise it searches.
# Bandcamp always comes first and has focus, with Cancel right below it: buying the track there is
# the best way to support the artist.
SEARCH_SITES = [
    ("Bandcamp", "bandcamp_search", False),
    ("Spotify", "spotify_search", False),
    ("YouTube", "youtube_search", False),
    ("Google", "google_search", True),
]
SEARCH_DEFAULT = 0
SEARCH_SPOTIFY = 1

# Songs in Recently played, numbered 1 to 10. The number keys pick them, with 0 for the 10th.
HISTORY_SHOWN = 10

# Formats to choose from in the settings. settings.ini can have any other strftime format.
MIN_COLS = 50

# The screen is redrawn this often
FRAME_SECONDS = 0.05
# How long to wait after Esc to tell a lone Esc from the start of a longer key sequence
ESC_DELAY_SECONDS = 0.05

# How long the metadata stream may be disconnected before the song info is marked as missing
METADATA_GRACE_SECONDS = 10
# How long a message stays in the status line
STATUS_MESSAGE_SECONDS = 2.0
# A new song's message stays longer, as it comes without a key press
SONG_MESSAGE_SECONDS = 5.0

# Scrolling of names too long to fit
MARQUEE_PAUSE = 2.0  # seconds to rest at the start of each loop
MARQUEE_SPEED = 4.0  # characters per second
MARQUEE_GAP = "  •  "  # between the end of the text and its start again, marking where the loop ends


def song_line(song):
    # The song on one line. Jingles and live shows say what they are, so they aren't taken for songs.
    artist, title = song.get("artist", ""), song.get("song", "")
    kind = song_kind(song)
    if kind == "jingle":
        return f"Jingle by {artist}" if artist else "Jingle"
    if kind == "live":
        # The title is just "Live on <station>"
        return f"Live: {artist}" if artist else title
    return " – ".join(part for part in (artist, title) if part)


def hotkey(text):
    # Menu labels mark their hotkey with tildes, Turbo Vision style: "E~x~it"
    parts = text.split("~")
    return parts[1].lower() if len(parts) > 1 else None


def theme_label(name):
    # The theme's name with its menu hotkey marked
    i = name.lower().index(THEME_HOTKEYS.get(name, name[0].lower()))
    return f"{name[:i]}~{name[i]}~{name[i + 1:]}"


def visible_len(text):
    return len(text.replace("~", ""))


# Semantic versioning (semver.org). Keep in step with the version in pyproject.toml.
VERSION = "2.0.0"

MAX_VOLUME = 99


def step_volume(volume, step):
    # Volume after a step of 1 or 10 up or down. Steps of 10 go to the next round ten, so the
    # volume lines up again after fine changes: 45 goes to 50 or 40. The top is 99, not 100.
    if abs(step) == 1:
        return min(MAX_VOLUME, max(0, volume + step))
    if step > 0:
        return min(MAX_VOLUME, (volume // 10 + 1) * 10)
    return max(0, (volume - 1) // 10 * 10)


def step_start_volume(volume, step):
    # The startup volume in the settings: "last", then 0 to 99
    if volume == "last":
        return 0 if step > 0 else "last"
    if volume == 0 and step < 0:
        return "last"
    return step_volume(volume, step)


def volume_bar(volume, width=10):
    # Each block is 10, and a block shows from 5 up, so 99 fills the bar. Any sound shows a block.
    full = min(width, max(1 if volume else 0, (volume + 5) // 10))
    return "█" * full, "░" * (width - full)


def parse_notifications(value):
    # The kinds the notifications setting turns on. It is "all", "off", or names separated by
    # commas, such as "songs, actions". Anything else means all.
    value = value.strip().lower()
    if value in ("off", "none", ""):
        return set()
    names = {name.strip() for name in value.split(",")}
    kinds = {kind for kind, _, name in NOTIFICATION_KINDS if name in names}
    return kinds or set(ALL_NOTIFICATIONS)


def format_notifications(kinds):
    # The other way round, for settings.ini
    if kinds >= ALL_NOTIFICATIONS:
        return "all"
    if not kinds:
        return "off"
    return ", ".join(name for kind, _, name in NOTIFICATION_KINDS if kind in kinds)


def describe_notifications(kinds):
    # Short text for the button in the settings dialog: how many kinds are on
    return f"{len(kinds & ALL_NOTIFICATIONS)} of {len(ALL_NOTIFICATIONS)}..."


def open_url(url):
    # Opens url in the default browser, or a file in its default app. Browsers started from a terminal can print messages to it,
    # which would mess up the interface, so their output goes nowhere.
    if sys.platform == "win32":
        os.startfile(url)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif shutil.which("xdg-open"):
        subprocess.Popen(
            ["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
        )
    elif not webbrowser.open(url):
        raise OSError("no browser found")


# Terminal sequences for the window title: set it, and save and restore the terminal's own title
SET_TITLE = "\x1b]2;{}\x07"
SAVE_TITLE = "\x1b[22;2t"
RESTORE_TITLE = "\x1b[23;2t"


def copy_to_clipboard(text):
    # Copies text with the system's own tool. Returns whether one was found.
    if sys.platform == "win32":
        commands = [["clip"]]
    elif sys.platform == "darwin":
        commands = [["pbcopy"]]
    else:
        commands = [["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]
        if not os.environ.get("WAYLAND_DISPLAY"):
            commands = commands[1:]
    for command in commands:
        if shutil.which(command[0]):
            # wl-copy and xclip stay in the background to hand out the text, so don't wait for them
            # to finish, and keep them off the terminal
            process = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            process.communicate(text.encode(), timeout=2)
            return True
    # Many terminals can set the clipboard themselves (OSC 52), but don't say whether they did
    write_terminal(f"\x1b]52;c;{base64.b64encode(text.encode()).decode()}\x07")
    return False


class WindowsConsoleMouse:
    # In cmd.exe and other classic console windows, QuickEdit mode makes a click select text, and
    # the program never sees it. It is turned off while the mouse is on, and put back after.
    ENABLE_MOUSE_INPUT = 0x10
    ENABLE_QUICK_EDIT_MODE = 0x40
    ENABLE_EXTENDED_FLAGS = 0x80

    def __init__(self):
        import ctypes

        self.kernel32 = ctypes.windll.kernel32
        self.handle = self.kernel32.GetStdHandle(-10)
        self.saved = None

    def get_mode(self):
        import ctypes

        mode = ctypes.c_uint32()
        if not self.kernel32.GetConsoleMode(self.handle, ctypes.byref(mode)):
            return None
        return mode.value

    def enable(self):
        mode = self.get_mode()
        if mode is None:
            return
        self.saved = mode
        mode = (mode | self.ENABLE_MOUSE_INPUT | self.ENABLE_EXTENDED_FLAGS) & ~self.ENABLE_QUICK_EDIT_MODE
        self.kernel32.SetConsoleMode(self.handle, mode)

    def disable(self):
        # Puts QuickEdit back as it was, keeping whatever else changed meanwhile
        mode = self.get_mode()
        if mode is None or self.saved is None:
            return
        quick_edit = self.saved & self.ENABLE_QUICK_EDIT_MODE
        mouse = self.saved & self.ENABLE_MOUSE_INPUT
        mode = (mode & ~(self.ENABLE_QUICK_EDIT_MODE | self.ENABLE_MOUSE_INPUT)) | quick_edit | mouse
        self.kernel32.SetConsoleMode(self.handle, mode | self.ENABLE_EXTENDED_FLAGS)
        self.saved = None


def on_windows_close(callback):
    # Calls callback when the console window is closed, or Windows logs off or shuts down. Windows
    # ends the process a few seconds later whatever happens, so callback must be quick.
    # Ctrl-C and Ctrl-Break are left to Python. Returns the handler, which must be kept: if it were
    # garbage collected, Windows would call freed memory.
    import ctypes
    from ctypes import wintypes

    # CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT
    close_events = {2, 5, 6}

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
    def handler(event):
        if event in close_events:
            callback()
            return True
        return False

    ctypes.windll.kernel32.SetConsoleCtrlHandler(handler, True)
    return handler


def write_terminal(*sequences):
    # Sends control sequences that don't draw anything
    if sys.stdout and sys.stdout.isatty():
        sys.stdout.write("".join(sequences))
        sys.stdout.flush()


def cycle(choices, current, step):
    # The choice step places from current. A current value that isn't among the choices (a format
    # removed from the list in settings.ini) comes first, so it can be got back to.
    if current not in choices:
        choices = [current] + choices
    return choices[(choices.index(current) + step) % len(choices)]


def format_time(fmt):
    # The time now in a strftime format from the settings. A broken format shows as "?".
    try:
        return time.strftime(fmt)
    except ValueError:
        return "?"


class RadioInterface:
    def __init__(self, loglevel=logging.INFO, logfile: str = LOG_FILE):
        self.logger = Logger(
            module_name=__name__,
            log_file=logfile,
            log_level=loglevel,
            streamhandler=False,
            filehandler=True,
        )
        # The log is kept across restarts, so mark where each run starts and ends
        self.logger.log.info("===== Player started =====")

        ### Read config ###
        self.config = settings.load()

        self.api = NightRideAPI(loglevel=loglevel, logfile=logfile)
        self.stations = self.api.stations

        self.VU_METER = settings.get_bool(self.config, "SETTINGS", "vu_meter")
        self.level_meter = LevelMeter(loglevel=loglevel, logfile=logfile)
        self.level_meter.enabled = self.VU_METER
        self.MOUSE = settings.get_bool(self.config, "SETTINGS", "mouse")
        # The clock and date formats, and the lists to choose from, without broken ones
        self.load_formats()
        # Show songs when they start in the audio, see song_delay
        self.SYNC = settings.get_bool(self.config, "SETTINGS", "sync_song_info")
        # Until the audio's delay is measured, a few seconds after it starts, use the last run's
        try:
            self.api.audioPlayer.lag = float(self.config["SETTINGS"].get("sync_lag", ""))
        except ValueError:
            pass
        # The sync problem last told about, so each is told once
        self.sync_problem_shown = None
        # Whether the terminal is reporting the mouse right now
        self.mouse_on = False
        self.windows_mouse = None
        # Clickable areas of the screen, made again on every draw: (row, first column, end column,
        # action). Later ones are on top.
        self.zones = []
        # The last click (time, row, column), to notice double-clicks, and whether the click being
        # handled is one
        self.last_click = (0.0, -1, -1)
        self.double_click = False
        self.CLOCK = settings.get_bool(self.config, "SETTINGS", "clock")
        self.DATE = settings.get_bool(self.config, "SETTINGS", "date")
        self.theme = self.config["SETTINGS"]["theme"]
        if self.theme not in THEMES:
            self.logger.log.warning(f"Unknown theme {self.theme!r}")
            self.theme = "Synthwave"
        # The chosen theme. self.theme differs from it while the Theme menu previews another one.
        self.saved_theme = self.theme
        start = self.start_volume_setting()
        if start == "last":
            start = settings.get_int(self.config, "SETTINGS", "last_volume", 0, MAX_VOLUME)
        self.volume = start
        # When the volume last changed and isn't saved yet as the last used one, or None
        self.volume_changed_at = None
        self.muted = False
        self.api.audioPlayer.set_volume(self.volume)
        self.station = self.config["SETTINGS"]["default_station"]
        if self.station == "last":
            self.station = self.config["SETTINGS"]["last_station"]
        if self.station not in self.stations:
            self.logger.log.warning(f"Station {self.station!r} is not in the station list")
            self.station = self.stations[0]

        # UI state. mode is one of the keys in STATUS_HINTS.
        self.mode = "main"
        self.running = True
        self.menu_index = 0
        self.menu_item = 0
        self.dialog_sel = 0
        self.dialog_scroll = 0
        # A short message in the status line, saying what the last key press did, and until when it shows
        self.message = ""
        self.message_until = 0.0
        # The station and song last seen, to notice when a new song starts
        self.seen_song = None
        # Stations dialog: whether "Play" has focus (otherwise "Cancel")
        self.stations_play = True
        self.list_height = 1
        self.menu_x = []
        # Scrolling texts: name => (text, when it started scrolling)
        self.marquees = {}
        # Settings dialog: the focused field (see SETTINGS_* below), and the values being edited.
        # Start is "last" or a station, the volume "last" or 0 to 99, the formats are strftime formats.
        self.settings_field = 0
        self.settings_start = "last"
        self.settings_volume = 0
        self.settings_clock = ""
        self.settings_date = ""
        self.settings_notify = set(ALL_NOTIFICATIONS)
        self.settings_sync = True
        # Notifications picker: the focused row (the kinds, then OK and Cancel), and the kinds ticked
        self.notify_field = 0
        self.notify_kinds = set()
        # Recently played dialog: the chosen song (0 is the newest), the first one shown, how many
        # fit, and whether "Find" has focus (otherwise "Close")
        self.history_sel = 0
        self.history_scroll = 0
        self.history_height = 1
        self.history_search = True
        # Find this song dialog: the song, the site with focus, and the screen to go back to
        self.search_song = {}
        self.search_choice = SEARCH_DEFAULT
        # The site to go back to from Cancel
        self.search_site = SEARCH_DEFAULT
        self.search_return = "main"
        # Exit dialog: whether "Yes" has focus
        self.exit_yes = True
        # Help dialog: first visible line, and how many lines fit
        self.help_scroll = 0
        self.help_height = len(HELP)
        # Stream info dialog: the first row shown, and how many fit
        self.info_scroll = 0
        self.info_height = 1

        if sys.platform == "win32" and sys.stdin and sys.stdin.isatty():
            # blessed reads the keys one byte at a time. In text mode, Windows holds back Enter to see
            # if a line feed follows, and the next read then fails with PermissionError.
            import msvcrt

            msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        if sys.platform == "win32":
            # Closing the window ends the program at once, without reaching the end of this method
            self.close_handler = on_windows_close(self.on_window_closed)
        self.term = blessed.Terminal()
        self.screen = Screen(self.term)
        # The window title shown, and the terminal's own title saved to put back on exit
        self.title = None
        write_terminal(SAVE_TITLE)
        try:
            with self.term.fullscreen(), self.term.cbreak(), self.term.hidden_cursor():
                self.main()
        except KeyboardInterrupt:
            # Ctrl-C quits like Alt-X
            pass
        except Exception as e:
            self.logger.log.exception(e)
            self.api.audioPlayer.shutdown()
            raise
        finally:
            # Clear our title, then restore the saved one. Terminals that can't restore titles are
            # left with an empty one, which most show as their default.
            write_terminal(SET_TITLE.format(""), RESTORE_TITLE)
            self.save_last_volume(now=True)
            self.logger.log.info("===== Player exited =====")
        self.api.audioPlayer.shutdown()

    def load_formats(self):
        # The clock and date formats in use and the lists Settings cycles through, leaving out
        # broken formats. A broken one in use is replaced by the first good one in its list, or
        # the default. settings.ini keeps what it has, so it can be fixed by hand.
        self.format_problems = []
        self.bad_formats = []
        for kind in ("clock", "date"):
            formats = []
            for fmt in settings.get_list(self.config, "SETTINGS", f"{kind}_formats"):
                problem = settings.format_problem(fmt)
                if problem:
                    self.format_problems.append(f"The {kind} format {fmt!r} in {kind}_formats {problem}")
                    self.bad_formats.append(fmt)
                elif fmt not in formats:
                    formats.append(fmt)
            current = self.config["SETTINGS"][f"{kind}_format"]
            problem = settings.format_problem(current)
            if problem:
                self.format_problems.append(f"The {kind} format {current!r} {problem}")
                self.bad_formats.append(current)
                current = formats[0] if formats else settings.DEFAULTS["SETTINGS"][f"{kind}_format"]
            setattr(self, f"{kind}_format", current)
            setattr(self, f"{kind}_formats", formats)
        for problem in self.format_problems:
            self.logger.log.warning(f"{problem}, so it is not used")

    def main(self):
        self.init_styles()
        # The log says what is wrong with each
        bad = list(dict.fromkeys(self.bad_formats))
        if bad:
            names = ", ".join(repr("".join(c if c.isprintable() else "?" for c in fmt)) for fmt in bad[:2])
            more = " and more" if len(bad) > 2 else ""
            plural = "s" if len(bad) > 1 else ""
            self.notify(f"Bad format{plural} {names}{more} in settings.ini, see the log", STATUS_MESSAGE_SECONDS * 4, kind="error")
        self.set_station(self.station)
        self.set_mouse(self.MOUSE)
        try:
            while self.running:
                self.read_keys()
                self.check_sync()
                self.check_new_song()
                self.save_last_volume()
                self.update_title()
                self.draw()
        finally:
            self.set_mouse(False)

    def set_mouse(self, on):
        # Starts or stops the terminal reporting clicks and the wheel
        if on == self.mouse_on:
            return
        try:
            if on:
                if sys.platform == "win32":
                    self.windows_mouse = self.windows_mouse or WindowsConsoleMouse()
                    self.windows_mouse.enable()
                # Turned on directly: blessed's own way first asks the terminal whether it can, and
                # some terminals never answer
                self.term._dec_mode_set_enabled(*MOUSE_MODES)
            else:
                self.term._dec_mode_set_disabled(*MOUSE_MODES)
                if self.windows_mouse:
                    self.windows_mouse.disable()
            self.mouse_on = on
        except Exception:
            self.logger.log.exception("Could not turn the mouse " + ("on" if on else "off"))

    def init_styles(self):
        # Called again when the theme changes
        term = self.term
        for name, (fg, bg, *flags) in THEMES[self.theme].items():
            style = term.color_rgb(*rgb(COLORS[fg])) + term.on_color_rgb(*rgb(COLORS[bg]))
            if "underline" in flags:
                style += term.underline
            self.screen.styles[name] = style
        # Clickable links: dialog values, underlined
        self.screen.styles["link"] = self.screen.styles["dialog_value"] + term.underline
        self.screen.invalidate()

    ### Input ###

    def read_keys(self):
        # Wait up to one frame for a key, then take any others that are waiting.
        # Keys are named the way blessed names them ("KEY_UP", "KEY_F1"), or are the character typed.
        key = self.term.inkey(timeout=FRAME_SECONDS, esc_delay=ESC_DELAY_SECONDS)
        while key:
            # Unknown sequences have no name. They are passed on as they are and match nothing.
            name = key.name or str(key)
            if name.startswith("KEY_ALT_") and len(name) == len("KEY_ALT_") + 1:
                name = f"ALT_{name[-1].lower()}"
            try:
                if name.startswith("MOUSE_"):
                    self.handle_mouse(name, *key.mouse_yx)
                else:
                    self.logger.log.debug(f"User pressed key {name!r} ({str(key)!r})")
                    self.handle_key(name)
            except Exception:
                # One bad key shouldn't stop the music
                self.logger.log.exception(f"Error handling key {name!r} ({str(key)!r})")
            key = self.term.inkey(timeout=0, esc_delay=ESC_DELAY_SECONDS)

    def handle_key(self, key):
        if key in ("KEY_F12", "ALT_x"):
            self.running = False
        elif self.mode == "menu":
            self.menu_key(key)
        elif self.mode == "stations":
            self.station_dialog_key(key)
        elif self.mode == "settings":
            self.settings_dialog_key(key)
        elif self.mode == "notifications":
            self.notifications_dialog_key(key)
        elif self.mode == "history":
            self.history_dialog_key(key)
        elif self.mode == "search":
            self.search_dialog_key(key)
        elif self.mode == "exit":
            self.exit_dialog_key(key)
        elif self.mode == "help":
            self.help_dialog_key(key)
        elif self.mode == "stream_info":
            self.stream_info_dialog_key(key)
        elif self.mode == "about":
            if key in ENTER_KEYS + ("KEY_ESCAPE", " ", "KEY_F1"):
                self.mode = "main"
        else:
            self.main_key(key)
        self.preview_theme()

    def preview_theme(self):
        # In the Theme menu, the highlighted theme shows right away. Enter chooses it. Anywhere else,
        # e.g. after Esc closes the menu, the chosen theme shows.
        theme = self.saved_theme
        if self.mode == "menu":
            item = self.menus()[self.menu_index][1][self.menu_item]
            if item is not None and item[0].replace("~", "") in THEMES:
                theme = item[0].replace("~", "")
        if theme != self.theme:
            self.theme = theme
            self.init_styles()

    def handle_mouse(self, name, y, x):
        # Names are like MOUSE_LEFT, MOUSE_CTRL_LEFT, MOUSE_LEFT_RELEASED and MOUSE_SCROLL_UP
        if "RELEASED" in name or "MOTION" in name:
            return
        self.logger.log.debug(f"Mouse {name} at row {y}, column {x}")
        if "SCROLL_UP" in name or "SCROLL_DOWN" in name:
            self.wheel(-1 if "SCROLL_UP" in name else 1)
        elif name.endswith("_LEFT"):
            self.click(y, x)
        self.preview_theme()

    def wheel(self, step):
        # Volume by one on the main screen, otherwise moves in the list that is open
        if self.mode == "main":
            self.change_volume(-step)
        elif self.mode in ("stations", "history", "help", "menu", "stream_info"):
            self.handle_key("KEY_DOWN" if step > 0 else "KEY_UP")

    def click(self, y, x):
        now = time.time()
        last_time, last_y, last_x = self.last_click
        self.double_click = now - last_time < DOUBLE_CLICK_SECONDS and (y, x) == (last_y, last_x)
        # A double-click doesn't start another one
        self.last_click = (0.0, -1, -1) if self.double_click else (now, y, x)
        for row, start, end, action in reversed(self.zones):
            if row == y and start <= x < end:
                if action:
                    action()
                return
        if self.mode == "menu":
            # A click outside an open menu closes it
            self.mode = "main"

    def zone(self, y, x, width, action):
        # Makes width columns from (y, x) clickable. action None only stops clicks reaching what is below.
        self.zones.append((y, x, x + width, action))

    def block(self, y, x, h, w):
        # Stops clicks on a window from reaching what is under it
        for row in range(y, y + h):
            self.zone(row, x, w, None)

    def main_key(self, key):
        if key in DIGITS and 1 <= int(key) <= min(9, len(self.stations)):
            self.set_station(self.stations[int(key) - 1])
        elif key == "KEY_LEFT":
            self.step_station(-1)
        elif key == "KEY_RIGHT":
            self.step_station(1)
        elif key in ("KEY_UP", "+", "="):
            self.change_volume(10)
        elif key in ("KEY_DOWN", "-"):
            self.change_volume(-10)
        elif key == "KEY_SHIFT_UP":
            self.change_volume(1)
        elif key == "KEY_SHIFT_DOWN":
            self.change_volume(-1)
        elif key == "v":
            self.toggle_vu_meter()
        elif key == "m":
            self.toggle_mute()
        elif key == "c":
            self.toggle_clock()
        elif key == "d":
            self.toggle_date()
        elif key in ("t", "T"):
            self.step_theme(1 if key == "t" else -1)
        elif key == "f":
            self.open_search()
        elif key == "KEY_F1":
            self.open_help()
        elif key == "KEY_F2":
            self.open_station_dialog()
        elif key == "KEY_F3":
            self.open_history()
        elif key == "KEY_F10":
            self.open_menu(0)
        elif key == "KEY_ESCAPE":
            self.mode = "exit"
            self.exit_yes = True
        elif key.startswith("ALT_"):
            self.open_menu_by_hotkey(key[-1])

    def menu_key(self, key):
        menus = self.menus()
        items = menus[self.menu_index][1]
        if key in ("KEY_ESCAPE", "KEY_F10"):
            self.mode = "main"
        elif key in ("KEY_LEFT", "KEY_RIGHT"):
            step = -1 if key == "KEY_LEFT" else 1
            self.open_menu((self.menu_index + step) % len(menus))
        elif key in ("KEY_UP", "KEY_DOWN"):
            step = -1 if key == "KEY_UP" else 1
            i = self.menu_item
            # Skip separators
            while True:
                i = (i + step) % len(items)
                if items[i] is not None:
                    break
            self.menu_item = i
        elif key in ENTER_KEYS:
            self.run_menu_item(items[self.menu_item])
        elif key.startswith("ALT_"):
            self.open_menu_by_hotkey(key[-1])
        elif len(key) == 1:
            for i, item in enumerate(items):
                if item is not None and hotkey(item[0]) == key.lower():
                    self.menu_item = i
                    self.run_menu_item(item)
                    break

    def station_dialog_key(self, key):
        last = len(self.stations) - 1
        list_keys = ("KEY_UP", "KEY_DOWN", "KEY_PGUP", "KEY_PGDOWN", "KEY_HOME", "KEY_END")
        if key in list_keys or key in DIGITS:
            # Picking a station puts the focus back on Play, so Enter never cancels by surprise
            self.stations_play = True
        if key in ("KEY_LEFT", "KEY_RIGHT", "KEY_TAB", "KEY_BTAB"):
            self.stations_play = not self.stations_play
        elif key == "KEY_UP":
            self.dialog_sel = max(0, self.dialog_sel - 1)
        elif key == "KEY_DOWN":
            self.dialog_sel = min(last, self.dialog_sel + 1)
        elif key == "KEY_PGUP":
            self.dialog_sel = max(0, self.dialog_sel - self.list_height)
        elif key == "KEY_PGDOWN":
            self.dialog_sel = min(last, self.dialog_sel + self.list_height)
        elif key == "KEY_HOME":
            self.dialog_sel = 0
        elif key == "KEY_END":
            self.dialog_sel = last
        elif key in DIGITS and 1 <= int(key) <= len(self.stations):
            self.dialog_sel = int(key) - 1
        elif key in ENTER_KEYS and self.stations_play:
            self.logger.log.debug(f"User selected station {self.stations[self.dialog_sel]} via F2")
            self.set_station(self.stations[self.dialog_sel])
            self.mode = "main"
        elif key in ENTER_KEYS + ("KEY_ESCAPE", "KEY_F2"):
            self.mode = "main"

    def settings_dialog_key(self, key):
        field = self.settings_field
        on_buttons = field in (SETTINGS_OK, SETTINGS_CANCEL)
        if key == "KEY_DOWN":
            # The buttons are one row: going down from the last field lands on OK
            self.settings_field = field if on_buttons else field + 1
        elif key == "KEY_UP":
            # Up from the buttons lands on the last field
            self.settings_field = SETTINGS_NOTIFY if on_buttons else max(SETTINGS_START, field - 1)
        elif key in ("KEY_TAB", "KEY_BTAB"):
            step = 1 if key == "KEY_TAB" else -1
            self.settings_field = (field + step) % (SETTINGS_CANCEL + 1)
        elif key in ("KEY_SHIFT_LEFT", "KEY_SHIFT_RIGHT") and field == SETTINGS_VOLUME:
            self.settings_volume = step_start_volume(self.settings_volume, -1 if key == "KEY_SHIFT_LEFT" else 1)
        elif key in ("KEY_LEFT", "KEY_RIGHT"):
            step = -1 if key == "KEY_LEFT" else 1
            if field == SETTINGS_START:
                self.settings_start = cycle(["last"] + self.stations, self.settings_start, step)
            elif field == SETTINGS_VOLUME:
                self.settings_volume = step_start_volume(self.settings_volume, step * 10)
            elif field == SETTINGS_CLOCK:
                self.settings_clock = cycle(self.clock_formats, self.settings_clock, step)
            elif field == SETTINGS_DATE:
                self.settings_date = cycle(self.date_formats, self.settings_date, step)
            elif field == SETTINGS_SYNC:
                self.settings_sync = not self.settings_sync
            elif field in (SETTINGS_OK, SETTINGS_CANCEL):
                self.settings_field = SETTINGS_CANCEL if field == SETTINGS_OK else SETTINGS_OK
        elif key in ENTER_KEYS + (" ",) and field == SETTINGS_NOTIFY:
            self.open_notifications()
        elif key in ENTER_KEYS and field != SETTINGS_CANCEL:
            self.config.set("SETTINGS", "default_station", self.settings_start)
            self.config.set("SETTINGS", "start_volume", str(self.settings_volume))
            self.config.set("SETTINGS", "clock_format", self.settings_clock)
            self.config.set("SETTINGS", "date_format", self.settings_date)
            self.clock_format = self.settings_clock
            self.date_format = self.settings_date
            self.config.set("SETTINGS", "notifications", format_notifications(self.settings_notify))
            self.config.set("SETTINGS", "sync_song_info", f"{self.settings_sync}")
            self.SYNC = self.settings_sync
            self.save_config()
            self.notify("Settings saved")
            self.mode = "main"
        elif key in ENTER_KEYS + ("KEY_ESCAPE",):
            self.mode = "main"

    def history_dialog_key(self, key):
        songs = self.history_songs()
        last = max(0, len(songs) - 1)
        if key in ("KEY_UP", "KEY_DOWN", "KEY_PGUP", "KEY_PGDOWN", "KEY_HOME", "KEY_END") or key in DIGITS:
            self.history_search = True
        if key in ("KEY_LEFT", "KEY_RIGHT", "KEY_TAB", "KEY_BTAB"):
            self.history_search = not self.history_search
        elif key == "KEY_UP":
            self.history_sel = max(0, self.history_sel - 1)
        elif key == "KEY_DOWN":
            self.history_sel = min(last, self.history_sel + 1)
        elif key == "KEY_PGUP":
            self.history_sel = max(0, self.history_sel - self.history_height)
        elif key == "KEY_PGDOWN":
            self.history_sel = min(last, self.history_sel + self.history_height)
        elif key == "KEY_HOME":
            self.history_sel = 0
        elif key == "KEY_END":
            self.history_sel = last
        elif key in DIGITS and (int(key) or 10) <= len(songs):
            self.history_sel = (int(key) or 10) - 1
        elif (key == "f" or (key in ENTER_KEYS and self.history_search)) and songs:
            self.open_search(songs[self.history_sel], back_to="history")
        elif key in ENTER_KEYS + ("KEY_ESCAPE", "KEY_F3"):
            self.mode = "main"

    def search_dialog_key(self, key):
        # The choices are the sites in a row and, on the row below, Cancel
        sites = len(SEARCH_SITES)
        on_cancel = self.search_choice == sites
        if key in ("KEY_TAB", "KEY_BTAB"):
            self.search_choice = (self.search_choice + (1 if key == "KEY_TAB" else -1)) % (sites + 1)
        elif key in ("KEY_LEFT", "KEY_RIGHT") and not on_cancel:
            self.search_choice = (self.search_choice + (1 if key == "KEY_RIGHT" else -1)) % sites
        elif key == "KEY_DOWN" and not on_cancel:
            self.search_site = self.search_choice
            self.search_choice = sites
        elif key == "KEY_UP" and on_cancel:
            # Back to the site that had focus before
            self.search_choice = self.search_site
        elif key in ENTER_KEYS and self.search_choice < sites:
            self.web_search(self.search_choice)
        elif key in ENTER_KEYS:
            self.mode = self.search_return
        elif len(key) == 1 and key.lower() in "bsyg":
            # Each site by its first letter
            self.web_search([name[0].lower() for name, _, _ in SEARCH_SITES].index(key.lower()))
        elif key == "KEY_ESCAPE":
            self.mode = self.search_return

    def help_dialog_key(self, key):
        last = max(0, len(HELP) - self.help_height)
        if key in ("KEY_UP", "KEY_PGUP"):
            step = 1 if key == "KEY_UP" else self.help_height
            self.help_scroll = max(0, self.help_scroll - step)
        elif key in ("KEY_DOWN", "KEY_PGDOWN"):
            step = 1 if key == "KEY_DOWN" else self.help_height
            self.help_scroll = min(last, self.help_scroll + step)
        elif key in ENTER_KEYS + ("KEY_ESCAPE", " ", "KEY_F1"):
            self.mode = "main"

    def stream_info_dialog_key(self, key):
        # Scrolls like Help when the window is too short for all of it. The drawing keeps the
        # scroll within the rows.
        if key in ("KEY_UP", "KEY_PGUP"):
            step = 1 if key == "KEY_UP" else self.info_height
            self.info_scroll = max(0, self.info_scroll - step)
        elif key in ("KEY_DOWN", "KEY_PGDOWN"):
            step = 1 if key == "KEY_DOWN" else self.info_height
            self.info_scroll += step
        elif key in ENTER_KEYS + ("KEY_ESCAPE", " "):
            self.mode = "main"

    def notifications_dialog_key(self, key):
        # A tick box for each kind, then OK and Cancel on one row
        boxes = len(NOTIFICATION_KINDS)
        ok, cancel = boxes, boxes + 1
        field = self.notify_field
        if key == "KEY_DOWN":
            self.notify_field = min(ok, field + 1) if field < ok else field
        elif key == "KEY_UP":
            self.notify_field = boxes - 1 if field >= ok else max(0, field - 1)
        elif key in ("KEY_TAB", "KEY_BTAB"):
            self.notify_field = (field + (1 if key == "KEY_TAB" else -1)) % (cancel + 1)
        elif key in ("KEY_LEFT", "KEY_RIGHT") and field >= ok:
            self.notify_field = cancel if field == ok else ok
        elif key == " " and field < ok:
            self.notify_kinds ^= {NOTIFICATION_KINDS[field][0]}
        elif key in ENTER_KEYS and field != cancel:
            self.settings_notify = set(self.notify_kinds)
            self.mode = "settings"
        elif key in ENTER_KEYS + ("KEY_ESCAPE",):
            self.mode = "settings"

    def exit_dialog_key(self, key):
        if key in ("KEY_LEFT", "KEY_RIGHT", "KEY_TAB", "KEY_BTAB"):
            self.exit_yes = not self.exit_yes
        elif key in ("y", "Y") or (key in ENTER_KEYS and self.exit_yes):
            self.running = False
        elif key in ("n", "N", "KEY_ESCAPE") or key in ENTER_KEYS:
            self.mode = "main"

    ### Actions ###

    def menus(self):
        # Each menu is (title, items). An item is (label, shortcut, action, checked, toggle), or None for a separator.
        # Choosing a toggle item keeps the menu open, so you can see its check mark change.
        # Radio is for listening, Options for what the window shows, Theme for its colours.
        return [
            (
                "~R~adio",
                [
                    ("~S~tations...", "F2", self.open_station_dialog, False, False),
                    ("~R~ecently played...", "F3", self.open_history, False, False),
                    ("~F~ind this song...", "F", self.open_search, False, False),
                    None,
                    ("~M~ute", "M", self.toggle_mute, self.muted, True),
                    None,
                    ("E~x~it", "Alt-X", self.quit, False, False),
                ],
            ),
            (
                "~O~ptions",
                [
                    ("~V~U meter", "V", self.toggle_vu_meter, self.VU_METER, True),
                    ("~C~lock", "C", self.toggle_clock, self.CLOCK, True),
                    ("~D~ate", "D", self.toggle_date, self.DATE, True),
                    ("Mo~u~se", None, self.toggle_mouse, self.MOUSE, True),
                    None,
                    ("~S~ettings...", None, self.open_settings, False, False),
                ],
            ),
            (
                "~T~heme",
                # The highlighted theme shows behind the menu (see preview_theme), and Enter chooses it
                [
                    (theme_label(name), None, lambda n=name: self.set_theme(n), name == self.saved_theme, False)
                    for name in THEMES
                ]
                + [None, ("~N~ext theme", "T", lambda: self.step_theme(1), False, True)],
            ),
            (
                "~H~elp",
                [
                    ("~K~eys...", "F1", self.open_help, False, False),
                    ("~U~ser manual", None, self.open_manual, False, False),
                    ("~S~tream info...", None, self.open_stream_info, False, False),
                    ("~N~ightride.fm on web", None, self.open_website, False, False),
                    None,
                    ("~A~bout...", None, self.open_about, False, False),
                ],
            ),
        ]

    def open_menu(self, index):
        self.mode = "menu"
        self.menu_index = index
        self.menu_item = 0
        # The Theme menu opens on the chosen theme, so nothing changes until the highlight moves
        for i, item in enumerate(self.menus()[index][1]):
            if item is not None and item[0].replace("~", "") == self.saved_theme:
                self.menu_item = i

    def open_menu_by_hotkey(self, letter):
        for i, (title, items) in enumerate(self.menus()):
            if hotkey(title) == letter:
                self.open_menu(i)

    def run_menu_item(self, item):
        label, shortcut, action, checked, toggle = item
        if not toggle:
            self.mode = "main"
        action()

    def open_about(self):
        self.mode = "about"

    def open_stream_info(self):
        self.mode = "stream_info"
        self.info_scroll = 0
        self.api.check_stream_format(self.station)

    ### Clicks ###

    def close_dialog(self):
        self.mode = "main"

    def click_menu(self, index):
        # A click on a menu's title opens it, or closes it if it is open
        if self.mode == "menu" and self.menu_index == index:
            self.mode = "main"
        else:
            self.open_menu(index)

    def click_menu_item(self, index):
        self.menu_item = index
        self.run_menu_item(self.menus()[self.menu_index][1][index])

    def click_station(self, index):
        self.dialog_sel = index
        self.stations_play = True
        if self.double_click:
            self.play_selected_station()

    def play_selected_station(self):
        self.stations_play = True
        self.station_dialog_key("\n")

    def click_setting(self, field, key=None):
        # Chooses a field in the settings, and does what key would do there. The picker field opens.
        self.settings_field = field
        if key:
            self.settings_dialog_key(key)
        elif field == SETTINGS_NOTIFY:
            self.open_notifications()

    def click_notification(self, field, key):
        self.notify_field = field
        self.notifications_dialog_key(key)

    def click_history(self, index):
        self.history_sel = index
        self.history_search = True
        if self.double_click:
            self.history_button(True)

    def history_button(self, search):
        self.history_search = search
        self.history_dialog_key("\n")

    def open_website(self):
        url = self.config["URLS"]["website"]
        self.mode = "main"
        self.logger.log.debug(f"Opening {url}")
        try:
            open_url(url)
            self.notify("Opened nightride.fm in the browser")
        except OSError as e:
            self.logger.log.error(f"Could not open {url}: {e}")
            self.notify("Could not open the browser", kind="error")

    def open_manual(self):
        # Opens the manual in the system's text editor, as the terminal window may be small.
        # Online if the file isn't there.
        self.mode = "main"
        path = find_manual()
        target = path or MANUAL_URL
        self.logger.log.debug(f"Opening {target}")
        try:
            open_url(target)
            self.notify("Opened the user manual" if path else "Opened the user manual on the web")
        except OSError as e:
            self.logger.log.error(f"Could not open {target}: {e}")
            self.notify("Could not open the user manual", kind="error")

    def open_help(self):
        self.mode = "help"
        self.help_scroll = 0

    def open_station_dialog(self):
        self.mode = "stations"
        self.dialog_sel = self.stations.index(self.station)
        self.stations_play = True

    def open_history(self):
        self.mode = "history"
        self.history_sel = 0
        self.history_scroll = 0
        self.history_search = True

    def history_songs(self):
        # The playing station's last songs heard, newest first. Not the jingles: they aren't songs.
        songs = [song for song in self.heard_history(self.station) if song_kind(song) != "jingle"]
        return list(reversed(songs))[:HISTORY_SHOWN]

    def song_delay(self, station=None):
        # Seconds from a song's start time in the song info to when it is heard. The song info
        # comes some seconds before the song starts in the live audio stream, and the audio heard
        # is behind the live stream by the past audio the server sent when the player connected.
        # Zero when not syncing, for other stations than the one playing, or when the delay isn't
        # known.
        if not self.SYNC or station not in (None, self.station):
            return 0
        lag = self.api.audioPlayer.lag
        if lag is None or self.api.gap_problem:
            return 0
        return lag + (self.api.gap or 0)

    def heard_history(self, station):
        # The station's songs that have started in the audio heard, oldest first. If none has,
        # the oldest known song, as nothing better is known.
        songs = list(self.api.history[station])
        delay = self.song_delay(station)
        if not delay:
            return songs
        heard = [song for song in songs if song["started_at"] + delay <= time.time()]
        return heard or songs[:1]

    def heard_song(self, station=None):
        # The song heard now on station (the playing one by default), or for other stations the
        # song the song info says is playing
        station = station or self.station
        if self.song_delay(station):
            songs = self.heard_history(station)
            if songs:
                return songs[-1]
        return self.api.now_playing.get(station, {})

    def check_sync(self):
        # Tells once about a problem syncing the song info with the audio. The log has the details.
        problem = None
        if self.SYNC:
            problem = self.api.audioPlayer.lag_problem or self.api.gap_problem
        if problem != self.sync_problem_shown:
            if problem:
                self.notify("Song info is not in sync with the audio", STATUS_MESSAGE_SECONDS * 2, kind="error")
            self.sync_problem_shown = problem
        # Keep the measurements, so the next start can sync right away. The audio's delay is
        # measured again a few seconds after each connection.
        gap = self.api.gap
        lag = self.api.audioPlayer.lag if self.api.audioPlayer.lag_measured else None
        changed = False
        for key, value in (("sync_gap", gap), ("sync_lag", lag)):
            if value is not None and self.config["SETTINGS"].get(key) != f"{value:.1f}":
                self.config.set("SETTINGS", key, f"{value:.1f}")
                changed = True
        if changed:
            self.save_config()

    def open_search(self, song=None, back_to="main"):
        # Asks where to look for a song, the one playing if none is given
        song = song or self.heard_song()
        if not (song.get("artist") or song.get("song")):
            self.notify("No song info to look for", kind="error")
            return
        if song_kind(song) == "jingle":
            self.notify("That's a jingle, not a song")
            return
        self.mode = "search"
        self.search_song = song
        self.search_choice = self.search_site = SEARCH_DEFAULT
        self.search_return = back_to

    def web_search(self, choice):
        name, setting, with_station = SEARCH_SITES[choice]
        spotify_id = self.search_song.get("spotify")
        if choice == SEARCH_SPOTIFY and spotify_id:
            url = self.config["URLS"]["spotify_track"].replace("{id}", urllib.parse.quote(spotify_id))
            done = "Opened the song on Spotify"
        else:
            words = [self.search_song.get("artist", ""), self.search_song.get("song", "")]
            if with_station:
                words.append(self.station)
            template = self.config["URLS"][setting]
            text = " ".join(word for word in words if word)
            # In the address's path (Spotify), spaces are %20. After a ?, + like a form sends.
            in_path = "?" not in template.split("{query}")[0]
            query = urllib.parse.quote(text, safe="") if in_path else urllib.parse.quote_plus(text)
            url = template.replace("{query}", query)
            done = f"Opened {name} in the browser"
        self.logger.log.debug(f"Opening {url}")
        try:
            open_url(url)
            self.notify(done)
        except OSError as e:
            self.logger.log.error(f"Could not open {url}: {e}")
            self.notify("Could not open the browser", kind="error")
        self.mode = self.search_return

    def open_settings(self):
        self.mode = "settings"
        self.settings_field = 0
        start = self.config["SETTINGS"]["default_station"]
        self.settings_start = start if start in self.stations else "last"
        self.settings_volume = self.start_volume_setting()
        self.settings_clock = self.clock_format
        self.settings_date = self.date_format
        self.settings_notify = parse_notifications(self.config["SETTINGS"]["notifications"])
        self.settings_sync = self.SYNC

    def open_notifications(self):
        # A picker on top of the settings dialog. Its choice is saved with the settings.
        self.mode = "notifications"
        self.notify_field = 0
        self.notify_kinds = set(self.settings_notify)

    def quit(self):
        self.running = False

    def set_station(self, station):
        self.logger.log.debug(f"Set station => {station}")
        try:
            self.station = station
            self.api.audioPlayer.play(station)
            if self.config["SETTINGS"]["last_station"] != station:
                self.config.set("SETTINGS", "last_station", station)
                self.save_config()
        except Exception as e:
            self.logger.log.error(f"Failed to set station to {station}")
            self.logger.log.error(e)

    def step_station(self, step):
        index = self.stations.index(self.station) + step
        if 0 <= index < len(self.stations):
            self.set_station(self.stations[index])

    def apply_volume(self):
        self.api.audioPlayer.set_volume(0 if self.muted else self.volume)

    def change_volume(self, step):
        # step is 1 or 10, up or down: see step_volume
        self.volume = step_volume(self.volume, step)
        self.muted = False
        self.apply_volume()
        self.volume_changed_at = time.time()

    def start_volume_setting(self):
        # The startup volume setting: "last", or 0 to 99. Anything else means "last".
        value = self.config["SETTINGS"]["start_volume"].strip().lower()
        if value in DIGITS or (len(value) == 2 and all(c in DIGITS for c in value)):
            return int(value)
        if value != "last":
            self.logger.log.warning(f"Setting start_volume = {value!r} is not last or 0 to 99, using last")
        return "last"

    def save_last_volume(self, now=False):
        # Saves the volume as the last used one, once it has stayed the same for a second, so
        # holding a key down doesn't write the settings file on every step
        if self.volume_changed_at is None:
            return
        if not now and time.time() - self.volume_changed_at < 1.0:
            return
        self.volume_changed_at = None
        if self.config["SETTINGS"]["last_volume"] != str(self.volume):
            self.config.set("SETTINGS", "last_volume", str(self.volume))
            self.save_config()

    def toggle_mute(self):
        self.muted = not self.muted
        self.apply_volume()
        self.notify("Muted" if self.muted else "Sound on")

    def toggle_vu_meter(self):
        self.VU_METER = not self.VU_METER
        self.level_meter.enabled = self.VU_METER
        self.config.set("SETTINGS", "vu_meter", f"{self.VU_METER}")
        self.save_config()
        self.notify(f"VU meter {'on' if self.VU_METER else 'off'}")

    def set_theme(self, name):
        self.theme = self.saved_theme = name
        self.init_styles()
        self.config.set("SETTINGS", "theme", name)
        self.save_config()
        self.notify(f"Theme: {name}")

    def toggle_clock(self):
        self.CLOCK = not self.CLOCK
        self.config.set("SETTINGS", "clock", f"{self.CLOCK}")
        self.save_config()
        self.notify(f"Clock {'on' if self.CLOCK else 'off'}")

    def toggle_mouse(self):
        self.MOUSE = not self.MOUSE
        self.set_mouse(self.MOUSE)
        self.config.set("SETTINGS", "mouse", f"{self.MOUSE}")
        self.save_config()
        self.notify(f"Mouse {'on' if self.MOUSE else 'off'}")

    def set_volume(self, volume):
        # A volume picked with the mouse
        self.volume = min(MAX_VOLUME, max(0, volume))
        self.muted = False
        self.apply_volume()
        self.volume_changed_at = time.time()

    def copy_email(self):
        if copy_to_clipboard(AUTHOR_EMAIL):
            self.notify("Copied the email address")
        else:
            self.notify("Copied the email address, if the terminal allows it")

    def open_repository(self):
        url = f"https://{REPOSITORY}"
        try:
            open_url(url)
            self.notify("Opened GitHub in the browser")
        except OSError as e:
            self.logger.log.error(f"Could not open {url}: {e}")
            self.notify("Could not open the browser", kind="error")

    def toggle_date(self):
        self.DATE = not self.DATE
        self.config.set("SETTINGS", "date", f"{self.DATE}")
        self.save_config()
        self.notify(f"Date {'on' if self.DATE else 'off'}")

    def step_theme(self, step):
        names = list(THEMES)
        self.set_theme(names[(names.index(self.saved_theme) + step) % len(names)])

    def on_window_closed(self):
        # Called from another thread when the console window is closed. Windows ends the process
        # right after, so only log it and stop the stream.
        self.logger.log.info("===== Player exited (window closed) =====")
        self.save_last_volume(now=True)
        self.api.audioPlayer.shutdown(timeout=1.0)

    def update_title(self):
        # The song and station in the terminal's window or tab title, for when the player is in the background
        song = song_line(self.heard_song())
        title = f"{song} · {self.station}" if song else f"{self.station} · Nightride.fm"
        # Control characters in a song name could end the title early
        title = "".join(c for c in title if c.isprintable())
        if title != self.title:
            self.title = title
            write_terminal(SET_TITLE.format(title))

    def notify(self, message, seconds=STATUS_MESSAGE_SECONDS, kind="action"):
        # Shows message above the status line for a moment, if the settings allow its kind:
        # "action" for what a key did, "song" for a new song, "error" for something going wrong
        if kind not in parse_notifications(self.config["SETTINGS"]["notifications"]):
            return
        self.message = message
        self.message_until = time.time() + seconds

    def check_new_song(self):
        # Announce a new song on the station that is playing. Not when changing stations: the new
        # station's song is already in the window then.
        info = self.heard_song()
        song = (self.station, info.get("artist", ""), info.get("song", ""))
        if song == self.seen_song:
            return
        if self.seen_song and self.seen_song[0] == self.station and (song[1] or song[2]):
            mark = "♪ " if song_kind(info) == "song" else ""
            self.notify(mark + song_line(info), SONG_MESSAGE_SECONDS, kind="song")
        self.seen_song = song

    def save_config(self):
        try:
            settings.save(self.config)
        except OSError as e:
            self.logger.log.error(f"Could not save settings: {e}")

    def marquee(self, name, text, width):
        # Returns the part of text to show in width characters. Text that doesn't fit scrolls:
        # it rests at the start, scrolls through, and loops. A new text starts from the beginning.
        if text_width(text) <= width:
            return text
        now = time.time()
        if self.marquees.get(name, (None,))[0] != text:
            self.marquees[name] = (text, now)
        loop = text + MARQUEE_GAP
        cycle = MARQUEE_PAUSE + len(loop) / MARQUEE_SPEED
        elapsed = (now - self.marquees[name][1]) % cycle
        offset = max(0, int((elapsed - MARQUEE_PAUSE) * MARQUEE_SPEED))
        return clip((loop + loop)[offset:], width)

    ### Drawing primitives ###

    def put(self, y, x, text, style):
        self.screen.put(y, x, text, style)

    def put_marked(self, y, x, text, style, hot_style):
        # Draw text with its ~hotkey~ in hot_style
        hot = False
        for part in text.split("~"):
            self.put(y, x, part, hot_style if hot else style)
            x += len(part)
            hot = not hot

    def scrollbar(self, y, x, height, first, shown, total, track_style, selected=None):
        # A scroll bar in the column x, from row y down height rows, for a list showing shown of
        # total rows from first on. Nothing if all of it fits. The arrows scroll by one when clicked.
        # In a list with a selected row, the thumb shows where that row is in the whole list, so
        # it moves with the selection even when the list doesn't scroll.
        if total <= shown:
            return
        self.put(y, x, "▲", "scrollbar")
        self.put(y + height - 1, x, "▼", "scrollbar")
        self.zone(y, x, 1, lambda: self.handle_key("KEY_UP"))
        self.zone(y + height - 1, x, 1, lambda: self.handle_key("KEY_DOWN"))
        track = height - 2
        if track > 0:
            self.fill(y + 1, x, track, 1, track_style, "░")
            # A solid block
            if selected is None:
                thumb = round(first / (total - shown) * (track - 1))
            else:
                thumb = round(selected / (total - 1) * (track - 1))
            self.put(y + 1 + thumb, x, " ", "scrollbar")

    def fill(self, y, x, h, w, style, char=" "):
        for row in range(y, y + h):
            self.put(row, x, char * w, style)

    def box(self, y, x, h, w, style, double=True, title=None, title_style=None):
        tl, tr, bl, br, hz, vt = "╔╗╚╝═║" if double else "┌┐└┘─│"
        self.put(y, x, tl + hz * (w - 2) + tr, style)
        for row in range(y + 1, y + h - 1):
            self.put(row, x, vt, style)
            self.put(row, x + w - 1, vt, style)
        self.put(y + h - 1, x, bl + hz * (w - 2) + br, style)
        if title:
            title = f" {title} "
            self.put(y, x + (w - len(title)) // 2, title, title_style or style)

    def window(self, y, x, h, w, body_style, border_style, title=None, title_style=None, double=True):
        # A filled box with a drop shadow. Clicks on it don't reach what is under it.
        self.block(y, x, h, w)
        self.fill(y + 1, x + w, h, 2, "shadow")
        self.fill(y + h, x + 2, 1, w, "shadow")
        self.fill(y, x, h, w, body_style)
        self.box(y, x, h, w, border_style, double, title, title_style)

    def button(self, y, x, label, focused=False, cancel=False, action=None):
        # Cancel buttons are red, others green. action runs when it is clicked.
        if action:
            self.zone(y, x, len(label), action)
        style = "button_cancel" if cancel else "button"
        if focused:
            # Mark the focused button with arrows, keeping its width
            label = "►" + label[1:-1] + "◄"
            style += "_focus"
        self.put(y, x, label, style)
        self.put(y, x + len(label), "▄", "button_shadow")
        self.put(y + 1, x + 1, "▀" * len(label), "button_shadow")

    ### Screens ###

    def draw(self):
        self.screen.begin()
        self.rows, self.cols = self.screen.height, self.screen.width
        self.zones = []

        # Room for the menu bar, the main window and its shadow, and the status line
        min_rows = self.window_height() + 3
        if self.rows < min_rows or self.cols < MIN_COLS:
            self.fill(0, 0, self.rows, self.cols, "window")
            message = f"Make the terminal at least {MIN_COLS}x{min_rows}"
            self.put(self.rows // 2, max(0, (self.cols - len(message)) // 2), message, "value")
            self.screen.render()
            return

        self.fill(0, 0, self.rows, self.cols, "desktop", "░")
        self.draw_main_window()
        self.draw_menu_bar()
        self.draw_status_line()
        if self.mode == "menu":
            self.draw_menu_dropdown()
        elif self.mode == "stations":
            self.draw_station_dialog()
        elif self.mode == "about":
            self.draw_about_dialog()
        elif self.mode == "stream_info":
            self.draw_stream_info_dialog()
        elif self.mode == "settings":
            self.draw_settings_dialog()
        elif self.mode == "notifications":
            self.draw_settings_dialog()
            self.draw_notifications_dialog()
        elif self.mode == "history":
            self.draw_history_dialog()
        elif self.mode == "search":
            self.draw_search_dialog()
        elif self.mode == "exit":
            self.draw_exit_dialog()
        elif self.mode == "help":
            self.draw_help_dialog()
        self.screen.render()

    def draw_menu_bar(self):
        self.fill(0, 0, 1, self.cols, "menu")
        self.menu_x = []
        x = 2
        for i, (title, items) in enumerate(self.menus()):
            selected = self.mode == "menu" and i == self.menu_index
            style, hot_style = ("menu_sel", "menu_sel_hot") if selected else ("menu", "menu_hot")
            self.put_marked(0, x, f" {title} ", style, hot_style)
            if self.mode in ("main", "menu"):
                self.zone(0, x, visible_len(title) + 2, lambda i=i: self.click_menu(i))
            self.menu_x.append(x)
            x += visible_len(title) + 2
        parts = []
        if self.DATE:
            parts.append(format_time(self.date_format))
        if self.CLOCK:
            parts.append(format_time(self.clock_format))
        # In a narrow terminal the date goes first, then the clock
        while parts and x + len("  ".join(parts)) + 2 > self.cols:
            parts.pop(0)
        if parts:
            text = "  ".join(parts)
            self.put(0, self.cols - len(text) - 2, text, "menu")

    def draw_status_line(self):
        y = self.rows - 1
        self.fill(y, 0, 1, self.cols, "menu")
        x = 1
        hints = self.mode
        if self.mode == "settings" and self.settings_field == SETTINGS_NOTIFY:
            hints = "settings_picker"
        for key, label in STATUS_HINTS[hints]:
            width = len(key) + 1 + len(label)
            if x + width >= self.cols:
                break
            self.put(y, x, key, "menu_hot")
            self.put(y, x + len(key) + 1, label, "menu")
            if key in HINT_KEYS:
                self.zone(y, x, width, lambda k=HINT_KEYS[key]: self.handle_key(k))
            x += width + 2
        if time.time() < self.message_until:
            # A message shows for a moment on the row above, at its start
            self.put(y - 1, 0, " " + clip(self.message, self.cols - 4) + " ", "menu_sel")

    def window_height(self):
        # The VU meter takes two more rows
        return 13 if self.VU_METER else 11

    def draw_main_window(self):
        h = self.window_height()
        w = min(60, self.cols - 4)
        top = 1 + (self.rows - 2 - (h + 1)) // 2
        left = (self.cols - (w + 2)) // 2
        self.window(top, left, h, w, "window", "window_border", "NIGHTRIDE.FM", "window_title")

        label_x = left + 3
        value_x = left + 13
        value_width = w - 16

        def separator(y):
            self.put(y, left, "╟" + "─" * (w - 2) + "╢", "window_border")

        if self.mode == "main":
            # Only when no menu or dialog is open
            self.zone(top + 2, label_x, w - 6, self.open_station_dialog)
            self.zone(top + 4, label_x, w - 6, self.open_search)
            self.zone(top + 5, label_x, w - 6, self.open_search)
            self.zone(top + 8, value_x, 1, lambda: self.change_volume(-10))
            for i in range(10):
                # Each block of the bar is 10: the first sets 10, the last 99
                self.zone(top + 8, value_x + 1 + i, 1, lambda i=i: self.set_volume((i + 1) * 10))
            self.zone(top + 8, value_x + 11, 1, lambda: self.change_volume(10))
            self.zone(top + 8, value_x + 13, 7, self.toggle_mute)

        number = self.stations.index(self.station) + 1
        self.put(top + 2, label_x, f"Station {number}", "label")
        self.put(top + 2, value_x, self.station, "value")
        if not self.api.connected and time.time() - self.api.disconnected_since > METADATA_GRACE_SECONDS:
            badge = " NO SONG INFO "
            self.put(top + 2, left + w - 3 - len(badge), badge, "warning")
        separator(top + 3)

        info = self.heard_song()
        self.put(top + 4, label_x, "Artist", "label")
        # Padded with a space on both sides, which shows as a block in themes that give them a background
        artist = self.marquee("artist", info.get("artist", ""), value_width)
        if artist:
            self.put(top + 4, value_x - 1, f" {artist} ", "artist")
        self.put(top + 5, label_x, "Song", "label")
        # Jingles and live shows get a label at the end of the row, so they aren't taken for songs
        kind = song_kind(info)
        badge = {"jingle": " JINGLE ", "live": " LIVE "}.get(kind, "")
        title = jingle_title(info.get("song", "")) if kind == "jingle" else info.get("song", "")
        song = self.marquee("song", title, value_width - (len(badge) + 2 if badge else 0))
        if song:
            self.put(top + 5, value_x - 1, f" {song} ", "song")
        if badge:
            self.put(top + 5, left + w - 3 - len(badge), badge, "badge")

        self.put(top + 6, label_x, "Played", "label")
        if self.api.audioPlayer.error:
            self.put(top + 6, value_x, " STREAM ERROR ", "error")
        elif self.api.audioPlayer.reconnecting:
            self.put(top + 6, value_x, " RECONNECTING ", "warning")
        elif self.api.audioPlayer.no_output or self.api.audioPlayer.stuck:
            self.put(top + 6, value_x, " NO AUDIO OUTPUT ", "error")
        elif "started_at" in info:
            seconds = max(0, int(time.time() - info["started_at"] - self.song_delay()))
            minutes, seconds = divmod(seconds, 60)
            self.put(top + 6, value_x, f"{minutes:02}:{seconds:02}", "value")
        else:
            self.put(top + 6, value_x, "--:--", "value")

        separator(top + 7)

        self.put(top + 8, label_x, "Volume", "label")
        self.put(top + 8, value_x, "◄", "label")
        full, empty = volume_bar(self.volume)
        self.put(top + 8, value_x + 1, full, "bar_full")
        self.put(top + 8, value_x + 1 + len(full), empty, "bar_empty")
        self.put(top + 8, value_x + 11, "►", "label")
        if self.muted or self.volume == 0:
            self.put(top + 8, value_x + 13, " MUTED ", "error")
        else:
            self.put(top + 8, value_x + 13, f"{self.volume:>2}", "number")

        if self.VU_METER:
            # The channel letters line up with the labels above
            self.draw_level_meter(top + 9, label_x, w - 8)

    def draw_level_meter(self, y, x, space):
        # Stereo LED meter. Bars show the average level, the lone lit segment is where the bar recently peaked.
        # Each segment is 1 dB, so the colour zones start on whole segments. Only a window too narrow for
        # that squeezes the scale into the space there is.
        if not self.level_meter.available:
            self.put(y, x, self.level_meter.missing, "label")
            return
        levels, peaks = self.level_meter.get()
        scale = CEILING_DB - FLOOR_DB
        width = min(space, round(scale))
        for row, (channel, level, peak) in enumerate(zip("LR", levels, peaks)):
            self.put(y + row, x, channel, "label")
            lit = round((level - FLOOR_DB) / scale * width)
            hold = round((peak - FLOOR_DB) / scale * width) - 1
            for i in range(width):
                db = FLOOR_DB + (i + 1) / width * scale
                zone = "vu_high" if db > -6 else "vu_mid" if db > -12 else "vu_low"
                # A thin bar that leaves room above and below, so the L and R rows don't run together
                self.put(y + row, x + 2 + i, "▮", zone if i < lit or i == hold else "vu_off")

    def draw_menu_dropdown(self):
        title, items = self.menus()[self.menu_index]
        label_width = max(visible_len(item[0]) for item in items if item)
        shortcut_width = max(len(item[1] or "") for item in items if item)
        # border, padding, check mark, space, label, (gap, shortcut), padding, border
        w = label_width + 6 + (shortcut_width + 2 if shortcut_width else 0)
        h = len(items) + 2
        y = 1
        x = min(self.menu_x[self.menu_index], self.cols - w - 2)
        self.window(y, x, h, w, "menu", "menu", double=False)

        for i, item in enumerate(items):
            row = y + 1 + i
            if item is None:
                self.put(row, x, "├" + "─" * (w - 2) + "┤", "menu")
                continue
            label, shortcut, action, checked, toggle = item
            self.zone(row, x + 1, w - 2, lambda i=i: self.click_menu_item(i))
            selected = i == self.menu_item
            style, hot_style = ("menu_sel", "menu_sel_hot") if selected else ("menu", "menu_hot")
            self.fill(row, x + 1, 1, w - 2, style)
            if checked:
                self.put(row, x + 2, "√", style)
            self.put_marked(row, x + 4, label, style, hot_style)
            if shortcut:
                self.put(row, x + w - 2 - len(shortcut), shortcut, style)

    def draw_station_dialog(self):
        count = len(self.stations)
        self.list_height = max(1, min(count, self.rows - 12))
        w = 44
        h = self.list_height + 9
        top = 1 + (self.rows - 2 - (h + 1)) // 2
        left = (self.cols - (w + 2)) // 2
        self.window(top, left, h, w, "dialog", "dialog_border", "Stations")

        # Keep the selection visible in the list
        if self.dialog_sel < self.dialog_scroll:
            self.dialog_scroll = self.dialog_sel
        elif self.dialog_sel >= self.dialog_scroll + self.list_height:
            self.dialog_scroll = self.dialog_sel - self.list_height + 1

        list_x = left + 2
        list_w = w - 4
        self.box(top + 1, list_x, self.list_height + 2, list_w, "dialog", double=False)
        for row in range(self.list_height):
            i = self.dialog_scroll + row
            if i >= count:
                break
            station = self.stations[i]
            playing = "♪" if station == self.station else " "
            text = f" {i + 1:>2}  {station}".ljust(list_w - 4) + playing + " "
            self.put(top + 2 + row, list_x + 1, text, "list_sel" if i == self.dialog_sel else "list")
            self.zone(top + 2 + row, list_x + 1, len(text), lambda i=i: self.click_station(i))

        # On the right edge of the list
        self.scrollbar(
            top + 2, list_x + list_w - 1, self.list_height, self.dialog_scroll, self.list_height, count, "dialog",
            selected=self.dialog_sel,
        )

        info = self.heard_song(self.stations[self.dialog_sel])
        info_y = top + self.list_height + 3
        self.put(info_y, left + 3, "Artist", "dialog")
        self.put(info_y, left + 11, self.marquee("stations_artist", info.get("artist", ""), w - 14), "dialog_value")
        self.put(info_y + 1, left + 3, "Song", "dialog")
        title = info.get("song", "")
        if song_kind(info) == "jingle":
            title = f"Jingle – {jingle_title(title)}"
        self.put(info_y + 1, left + 11, self.marquee("stations_song", title, w - 14), "dialog_value")

        buttons_y = top + h - 3
        self.button(buttons_y, left + w // 2 - 12, "  Play  ", self.stations_play, action=self.play_selected_station)
        self.button(buttons_y, left + w // 2 + 3, " Cancel ", not self.stations_play, cancel=True, action=self.close_dialog)

    def draw_settings_dialog(self):
        w = 44
        h = 17
        top = 1 + (self.rows - 2 - (h + 1)) // 2
        left = (self.cols - (w + 2)) // 2
        self.window(top, left, h, w, "dialog", "dialog_border", "Settings")

        volume = self.settings_volume
        if volume == "last":
            volume_text = f"{'Last used':<13}"
        else:
            volume_text = "".join(volume_bar(volume)) + f" {volume:>2}"
        start = "Last played" if self.settings_start == "last" else self.settings_start
        # The formats are shown as the time now looks in them
        fields = [
            ("Startup station", f"◄ {clip(start, 13):<13} ►"),
            ("Startup volume", f"◄ {volume_text} ►"),
            ("Clock format", f"◄ {clip(format_time(self.settings_clock), 13):<13} ►"),
            ("Date format", f"◄ {clip(format_time(self.settings_date), 13):<13} ►"),
            ("Sync song info", f"◄ {'On' if self.settings_sync else 'Off':<13} ►"),
            # A button that opens a picker, with how many kinds are on
            ("Notifications", f"{describe_notifications(self.settings_notify):^17}"),
        ]
        for i, (label, value) in enumerate(fields):
            y = top + 2 + i * 2
            self.put(y, left + 3, label, "dialog")
            if i == SETTINGS_NOTIFY:
                self.button(
                    y, left + 21, f" {value} ", i == self.settings_field,
                    action=self.mode == "settings" and (lambda: self.click_setting(SETTINGS_NOTIFY)),
                )
            else:
                self.put(y, left + 21, f" {value} ", "list_sel" if i == self.settings_field else "list")
            if self.mode == "settings":
                # A click on the field chooses it, on its arrows changes it. The picker opens on a click.
                self.zone(y, left + 3, w - 6, lambda i=i: self.click_setting(i))
                if i != SETTINGS_NOTIFY:
                    self.zone(y, left + 21, 3, lambda i=i: self.click_setting(i, "KEY_LEFT"))
                    self.zone(y, left + 21 + len(value) - 1, 3, lambda i=i: self.click_setting(i, "KEY_RIGHT"))

        buttons_y = top + h - 3
        clickable = self.mode == "settings"
        self.button(
            buttons_y,
            left + w // 2 - 12,
            "   OK   ",
            self.settings_field == SETTINGS_OK,
            action=clickable and (lambda: self.click_setting(SETTINGS_OK, "\n")),
        )
        self.button(
            buttons_y,
            left + w // 2 + 3,
            " Cancel ",
            self.settings_field == SETTINGS_CANCEL,
            cancel=True,
            action=clickable and self.close_dialog,
        )

    def draw_notifications_dialog(self):
        w = 32
        boxes = len(NOTIFICATION_KINDS)
        h = boxes + 6
        top = 1 + (self.rows - 2 - (h + 1)) // 2
        left = (self.cols - (w + 2)) // 2
        self.window(top, left, h, w, "dialog", "dialog_border", "Notifications")

        for i, (kind, label, _) in enumerate(NOTIFICATION_KINDS):
            mark = "√" if kind in self.notify_kinds else " "
            text = f" [{mark}] {label:<{w - 12}}"
            self.put(top + 2 + i, left + 3, text, "list_sel" if i == self.notify_field else "list")
            self.zone(top + 2 + i, left + 3, len(text), lambda i=i: self.click_notification(i, " "))

        buttons_y = top + h - 3
        self.button(
            buttons_y, left + w // 2 - 12, "   OK   ", self.notify_field == boxes,
            action=lambda: self.click_notification(boxes, "\n"),
        )
        self.button(
            buttons_y, left + w // 2 + 3, " Cancel ", self.notify_field == boxes + 1, cancel=True,
            action=lambda: self.click_notification(boxes + 1, "\n"),
        )

    def draw_history_dialog(self):
        songs = self.history_songs()
        w = min(60, self.cols - 4)
        self.history_height = max(1, min(len(songs), self.rows - 10))
        h = self.history_height + 7
        top = 1 + (self.rows - 2 - (h + 1)) // 2
        left = (self.cols - (w + 2)) // 2
        self.window(top, left, h, w, "dialog", "dialog_border", f"Recently Played: {self.station}")

        # Keep the chosen song visible
        if self.history_sel < self.history_scroll:
            self.history_scroll = self.history_sel
        elif self.history_sel >= self.history_scroll + self.history_height:
            self.history_scroll = self.history_sel - self.history_height + 1

        list_x = left + 2
        list_w = w - 4
        self.box(top + 1, list_x, self.history_height + 2, list_w, "dialog", double=False)
        if not songs:
            self.put(top + 2, list_x + 1, " No songs yet".ljust(list_w - 2), "list")
        for row in range(self.history_height):
            i = self.history_scroll + row
            if i >= len(songs):
                break
            song = songs[i]
            started = time.strftime("%H:%M", time.localtime(song["started_at"] + self.song_delay()))
            text = clip(f" {i + 1:>2}  {started}  {song_line(song)}", list_w - 3).ljust(list_w - 2)
            self.put(top + 2 + row, list_x + 1, text, "list_sel" if i == self.history_sel else "list")
            self.zone(top + 2 + row, list_x + 1, list_w - 2, lambda i=i: self.click_history(i))
        self.scrollbar(
            top + 2, list_x + list_w - 1, self.history_height, self.history_scroll, self.history_height, len(songs), "dialog",
            selected=self.history_sel,
        )

        buttons_y = top + h - 3
        self.button(
            buttons_y, left + w // 2 - 12, "  Find  ", self.history_search,
            action=lambda: self.history_button(True),
        )
        self.button(
            buttons_y, left + w // 2 + 3, " Close  ", not self.history_search, cancel=True,
            action=lambda: self.history_button(False),
        )

    def draw_search_dialog(self):
        w = 48
        h = 10
        top = 1 + (self.rows - 2 - (h + 1)) // 2
        left = (self.cols - (w + 2)) // 2
        self.window(top, left, h, w, "dialog", "dialog_border", "Find This Song")

        def centered(y, text, style):
            text = clip(text, w - 4)
            self.put(y, left + (w - text_width(text)) // 2, text, style)

        song = self.search_song
        centered(top + 2, song_line(song), "dialog_value")
        centered(top + 4, "Look for it on", "dialog")
        labels = [f" {name} " for name, _, _ in SEARCH_SITES]
        x = first_x = left + (w - sum(len(label) + 2 for label in labels) + 2) // 2
        for i, label in enumerate(labels):
            self.button(top + 5, x, label, i == self.search_choice, action=lambda i=i: self.web_search(i))
            x += len(label) + 2
        # Cancel goes below the first site
        self.button(
            top + 7, first_x, " Cancel ", self.search_choice == len(SEARCH_SITES), cancel=True,
            action=lambda: self.handle_key("KEY_ESCAPE"),
        )

    def draw_help_dialog(self):
        w = 48
        # Shrink to fit short terminals, and scroll what doesn't fit
        self.help_height = max(1, min(len(HELP), self.rows - 9))
        self.help_scroll = min(self.help_scroll, len(HELP) - self.help_height)
        h = self.help_height + 6
        top = 1 + (self.rows - 2 - (h + 1)) // 2
        left = (self.cols - (w + 2)) // 2
        self.window(top, left, h, w, "dialog", "dialog_border", "Help")

        for row in range(self.help_height):
            line = HELP[self.help_scroll + row]
            y = top + 2 + row
            if line is None:
                continue
            keys, description = line
            if description is None:
                self.put(y, left + 3, keys, "dialog_value")
            else:
                self.put(y, left + 5, keys, "dialog_key")
                self.put(y, left + 19, description, "dialog")

        # On the right edge of the window
        self.scrollbar(top + 2, left + w - 1, self.help_height, self.help_scroll, self.help_height, len(HELP), "dialog_border")
        self.button(top + h - 3, left + (w - 8) // 2, "   OK   ", True, action=self.close_dialog)

    def draw_exit_dialog(self):
        w = 34
        h = 8
        top = 1 + (self.rows - 2 - (h + 1)) // 2
        left = (self.cols - (w + 2)) // 2
        self.window(top, left, h, w, "dialog", "dialog_border", "Exit")

        question = "Quit Nightride?"
        self.put(top + 2, left + (w - len(question)) // 2, question, "dialog")
        buttons_y = top + h - 3
        self.button(buttons_y, left + w // 2 - 11, "  Yes   ", self.exit_yes, action=self.quit)
        self.button(buttons_y, left + w // 2 + 2, "   No   ", not self.exit_yes, cancel=True, action=self.close_dialog)

    def draw_about_dialog(self):
        w = 44
        h = 13
        top = 1 + (self.rows - 2 - (h + 1)) // 2
        left = (self.cols - (w + 2)) // 2
        self.window(top, left, h, w, "dialog", "dialog_border", "About")

        def centered(y, text, style, action=None):
            x = left + (w - len(text)) // 2
            self.put(y, x, text, style)
            if action:
                self.zone(y, x, len(text), action)

        centered(top + 2, "NIGHTRIDE", "dialog_value")
        centered(top + 3, "Player for Nightride.fm", "dialog")
        centered(top + 4, f"Version {VERSION}", "dialog")
        centered(top + 6, "Matias Räisänen 2026", "dialog")
        # The address is copied, as many people have no mail program set up for mailto: links
        centered(top + 7, AUTHOR_EMAIL, "link", self.copy_email)
        centered(top + 8, REPOSITORY, "link", self.open_repository)
        self.button(top + 10, left + (w - 8) // 2, "   OK   ", True, action=self.close_dialog)


    def stream_info(self):
        # The rows of Help > Stream info: (label, value, style of the value)
        player = self.api.audioPlayer
        stats = player.stats
        now = time.time()
        rows = [("Station", self.station, "dialog_value")]
        rows.append(("Address", player.url.split("://")[-1], "dialog_value"))

        if player.error:
            status = ("Stream error, still trying", "error")
        elif player.reconnecting:
            status = ("Reconnecting", "warning")
        elif player.no_output or player.stuck:
            status = ("No audio output", "error")
        elif player.playing_since is None:
            status = ("Stopped", "warning")
        elif stats is None:
            status = ("Connecting", "warning")
        else:
            status = (f"Playing for {duration(now - player.playing_since)}", "dialog_value")
        rows.append(("Status", *status))

        fmt = self.api.stream_format.get(self.station)
        if fmt is None:
            rows.append(("Format", "Checking...", "dialog"))
        elif "error" in fmt:
            rows.append(("Format", "Could not check, see the log", "warning"))
        else:
            kind = {"audio/mpeg": "MP3", "audio/aac": "AAC", "audio/aacp": "AAC", "audio/ogg": "Ogg"}.get(
                fmt["type"], fmt["type"] or "?"
            )
            parts = [kind]
            if fmt["kbits"]:
                parts.append(f"{fmt['kbits']} kbit/s")
            if fmt["samplerate"].isdigit():
                parts.append(f"{int(fmt['samplerate']) / 1000:g} kHz")
            if fmt["channels"]:
                parts.append({"1": "mono", "2": "stereo"}.get(fmt["channels"], f"{fmt['channels']} channels"))
            rows.append(("Format", ", ".join(parts), "dialog_value"))

        if stats:
            received = f"{stats['received'] / 1_000_000:.1f} MB"
            if stats["kbits"]:
                received += f" at {stats['kbits']:.0f} kbit/s"
            rows.append(("Received", received, "dialog_value"))
            problems = [
                f"{count} {name}"
                for count, name in (
                    (stats["lost"], "lost"), (stats["corrupted"], "broken"), (stats["discontinuities"], "gaps")
                )
                if count
            ]
            rows.append(("Dropouts", ", ".join(problems) if problems else "None", "warning" if problems else "dialog_value"))
        else:
            rows.append(("Received", "-", "dialog"))
            rows.append(("Dropouts", "-", "dialog"))
        rows.append(("Reconnects", str(player.reconnects) if player.reconnects else "None", "dialog_value"))

        if player.lag_problem:
            rows.append(("Behind live", "Can't tell, see the log", "warning"))
        elif player.lag is None:
            rows.append(("Behind live", "Measuring...", "dialog"))
        else:
            rows.append(("Behind live", f"{player.lag:.1f} s", "dialog_value"))

        # The connection to nightride.fm's song info, which says what each station plays
        if self.api.connected:
            rows.append(("Song info feed", "Connected", "dialog_value"))
        else:
            rows.append(("Song info feed", f"Disconnected for {duration(now - self.api.disconnected_since)}", "warning"))
        if self.api.gap_problem:
            rows.append(("Song info gap", "Can't tell, see the log", "warning"))
        elif self.api.gap is None:
            rows.append(("Song info gap", "Not measured yet", "dialog"))
        else:
            measured = self.api.gap_measured_at
            when = f", measured {time.strftime('%H:%M', time.localtime(measured))}" if measured else ", from before"
            rows.append(("Song info gap", f"{self.api.gap:.1f} s{when}", "dialog_value"))
        delay = self.song_delay()
        if not self.SYNC:
            rows.append(("Sync", "Off", "dialog_value"))
        elif delay:
            rows.append(("Sync", f"Songs show {delay:.1f} s after the info", "dialog_value"))
        else:
            rows.append(("Sync", "Not in sync yet", "warning"))
        return rows

    def draw_stream_info_dialog(self):
        rows = self.stream_info()
        w = min(56, self.cols - 4)
        # Shrink to fit short terminals, and scroll what doesn't fit
        self.info_height = max(1, min(len(rows), self.rows - 9))
        self.info_scroll = max(0, min(self.info_scroll, len(rows) - self.info_height))
        h = self.info_height + 6
        top = 1 + (self.rows - 2 - (h + 1)) // 2
        left = (self.cols - (w + 2)) // 2
        self.window(top, left, h, w, "dialog", "dialog_border", "Stream Info")
        # On the right edge of the window
        self.scrollbar(top + 2, left + w - 1, self.info_height, self.info_scroll, self.info_height, len(rows), "dialog_border")
        shown = rows[self.info_scroll:self.info_scroll + self.info_height]
        for i, (label, value, style) in enumerate(shown):
            self.put(top + 2 + i, left + 3, label, "dialog")
            if style in ("warning", "error"):
                # Marked like the badges on the main screen, padded with a space on both sides
                self.put(top + 2 + i, left + 18, f" {clip(value, w - 23)} ", style)
            else:
                self.put(top + 2 + i, left + 19, clip(value, w - 22), style)
        self.button(top + h - 3, left + (w - 8) // 2, "   OK   ", True, action=self.close_dialog)


def duration(seconds):
    # Like "45 s", "12 min" or "2 h 5 min"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{seconds // 60} min"
    return f"{seconds // 3600} h {seconds % 3600 // 60} min"


def test_stream(station, sound=True):
    # Plays a station for a few seconds without the interface. Returns True if it played.
    from audio_player import AudioPlayer

    config = settings.load()
    vlc_args = () if sound else ("--aout=dummy",)
    player = AudioPlayer(config["URLS"]["audio_stream_base_url"], vlc_args=vlc_args)
    print(f"Connecting to {station}...")
    player.play(station)
    if not player.started.wait(20):
        print("FAILED: the stream did not start. See the log for details:", LOG_FILE)
        return False
    print("Playing. Listening for 5 seconds...")
    time.sleep(5)
    ok = not player.dropped
    player.shutdown()
    print("OK" if ok else f"FAILED: the stream stopped. See the log for details: {LOG_FILE}")
    return ok


def main():
    # Entry point of the nightride command
    parser = argparse.ArgumentParser(prog="nightride", description="Player for Nightride FM synthwave radio")
    parser.add_argument(
        "--test-stream",
        metavar="STATION",
        nargs="?",
        const="chillsynth",
        help="play a station for a few seconds without the interface, to check that audio works",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument("--debug", action="store_true", help="log every key press and more, for finding bugs")
    # With --test-stream: decode the stream but don't play it, for testing on machines without sound
    parser.add_argument("--no-sound", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    try:
        if args.test_stream:
            sys.exit(0 if test_stream(args.test_stream, sound=not args.no_sound) else 1)
        RadioInterface(loglevel=logging.DEBUG if args.debug else logging.INFO)
    except Exception:
        traceback.print_exc()
        print(f"\nThe player crashed. The log is in {LOG_FILE}")
        if getattr(sys, "frozen", False) and sys.stdin and sys.stdin.isatty():
            # The Windows build may have been started by double-clicking, and its window closes when
            # it exits. Keep it open so the error can be read.
            input("Press Enter to close")
        sys.exit(1)


if __name__ == "__main__":
    main()
