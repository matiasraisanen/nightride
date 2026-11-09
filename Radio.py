import configparser
import curses
import logging
import time

from logger import Logger
from paths import LOG_FILE, SETTINGS_FILE

from LevelMeter import CEILING_DB, FLOOR_DB, LevelMeter
from NightrideAPI import NightRideAPI

# The 16 colours of the VGA text mode palette, as (closest xterm-256 colour, basic curses colour, bright).
# On 256-colour terminals the exact xterm colours are used, so the look doesn't depend on the terminal's theme.
VGA = {
    "black": (16, curses.COLOR_BLACK, False),
    "blue": (19, curses.COLOR_BLUE, False),
    "green": (34, curses.COLOR_GREEN, False),
    "cyan": (37, curses.COLOR_CYAN, False),
    "red": (124, curses.COLOR_RED, False),
    "lightgray": (248, curses.COLOR_WHITE, False),
    "darkgray": (240, curses.COLOR_BLACK, True),
    "lightblue": (63, curses.COLOR_BLUE, True),
    "lightgreen": (83, curses.COLOR_GREEN, True),
    "lightcyan": (87, curses.COLOR_CYAN, True),
    "lightred": (203, curses.COLOR_RED, True),
    "yellow": (227, curses.COLOR_YELLOW, True),
    "white": (231, curses.COLOR_WHITE, True),
}

# Style name => (foreground, background)
STYLES = {
    "desktop": ("lightgray", "blue"),
    "menu": ("black", "lightgray"),
    "menu_hot": ("red", "lightgray"),
    "menu_sel": ("black", "green"),
    "menu_sel_hot": ("red", "green"),
    "window": ("lightgray", "blue"),
    "window_border": ("white", "blue"),
    "window_title": ("yellow", "blue"),
    "label": ("cyan", "blue"),
    "value": ("white", "blue"),
    "number": ("yellow", "blue"),
    "bar_full": ("lightcyan", "blue"),
    "bar_empty": ("cyan", "blue"),
    "vu_low": ("lightgreen", "blue"),
    "vu_mid": ("yellow", "blue"),
    "vu_high": ("lightred", "blue"),
    "vu_off": ("lightblue", "blue"),
    "error": ("white", "red"),
    "dialog": ("black", "lightgray"),
    "dialog_border": ("white", "lightgray"),
    "dialog_value": ("blue", "lightgray"),
    "list": ("black", "cyan"),
    "list_sel": ("white", "blue"),
    "button": ("black", "green"),
    "button_focus": ("white", "green"),
    "button_cancel": ("lightgray", "red"),
    "button_cancel_focus": ("white", "red"),
    "button_shadow": ("black", "lightgray"),
    "shadow": ("darkgray", "black"),
}

# Key hints on the bottom status line, per screen
STATUS_HINTS = {
    "main": [
        ("F1", "Help"),
        ("F2", "Browse"),
        ("F10", "Menu"),
        ("←→", "Station"),
        ("↑↓", "Volume"),
        ("Alt-X", "Exit"),
    ],
    "menu": [("←→", "Menus"), ("↑↓", "Select"), ("Enter", "Choose"), ("Esc", "Close")],
    "stations": [("↑↓", "Station"), ("←→", "Button"), ("Enter", "Select"), ("Esc", "Cancel")],
    "about": [("Enter", "Close")],
    "help": [("↑↓", "Scroll"), ("Enter", "Close")],
    "exit": [("←→", "Move"), ("Enter", "Select"), ("Y", "Yes"), ("N", "No"), ("Esc", "Cancel")],
    "settings": [("↑↓", "Move"), ("←→", "Change"), ("Tab", "Next"), ("Enter", "OK"), ("Esc", "Cancel")],
}

ENTER_KEYS = ("\n", "\r", "KEY_ENTER")

# Contents of the help dialog: (keys, description) rows, a heading (keys only), or None for a blank line
HELP = [
    ("Main screen", None),
    ("←→  1-9", "Change station"),
    ("↑↓", "Volume"),
    ("M", "Mute"),
    ("V", "VU meter on/off"),
    ("F2", "Browse stations"),
    ("F10", "Menus, or Alt + red letter"),
    ("F1", "This help"),
    ("Esc", "Exit, asks first"),
    ("Alt-X  F12", "Exit right away"),
    None,
    ("Menus and dialogs", None),
    ("↑↓  ←→  Tab", "Move"),
    ("Enter", "Choose"),
    ("Esc", "Close or cancel"),
]

# Focusable items in the settings dialog, top to bottom
SETTINGS_STATION, SETTINGS_VOLUME, SETTINGS_OK, SETTINGS_CANCEL = range(4)

MIN_COLS = 50

# Scrolling of names too long to fit
MARQUEE_PAUSE = 2.0  # seconds to rest at the start of each loop
MARQUEE_SPEED = 4.0  # characters per second
MARQUEE_GAP = "  •  "  # between the end of the text and its start again, marking where the loop ends


def hotkey(text):
    # Menu labels mark their hotkey with tildes, Turbo Vision style: "E~x~it"
    parts = text.split("~")
    return parts[1].lower() if len(parts) > 1 else None


def visible_len(text):
    return len(text.replace("~", ""))


class RadioInterface:
    def __init__(self, loglevel=logging.INFO, logfile: str = LOG_FILE):
        self.logger = Logger(
            module_name=__name__,
            log_file=logfile,
            log_level=loglevel,
            delete_old_logfile=True,
            streamhandler=False,
            filehandler=True,
        )

        ### Read config ###
        self.config = configparser.ConfigParser()
        self.config.read(SETTINGS_FILE)

        self.api = NightRideAPI(loglevel=loglevel, logfile=logfile)
        self.stations = self.api.stations

        self.VU_METER = self.config.getboolean("SETTINGS", "VU_METER")
        self.level_meter = LevelMeter(loglevel=loglevel, logfile=logfile)
        self.level_meter.enabled = self.VU_METER
        self.CLOCK = self.config.getboolean("SETTINGS", "clock", fallback=True)
        self.volume = min(9, max(0, self.config.getint("SETTINGS", "startup_volume", fallback=4)))
        self.muted = False
        self.api.audioPlayer.set_volume(self.volume)
        self.station = self.config["SETTINGS"]["default_station"]
        self.version = "v2.0"

        # UI state. mode is one of the keys in STATUS_HINTS.
        self.mode = "main"
        self.running = True
        self.menu_index = 0
        self.menu_item = 0
        self.dialog_sel = 0
        self.dialog_scroll = 0
        # Browse dialog: whether "Play" has focus (otherwise "Cancel")
        self.browse_play = True
        self.list_height = 1
        self.menu_x = []
        # Scrolling texts: name => (text, when it started scrolling)
        self.marquees = {}
        # Settings dialog: the focused field (see SETTINGS_* below), and the values being edited
        self.settings_field = 0
        self.settings_station = 0
        self.settings_volume = 0
        # Exit dialog: whether "Yes" has focus
        self.exit_yes = True
        # Help dialog: first visible line, and how many lines fit
        self.help_scroll = 0
        self.help_height = len(HELP)

        try:
            curses.wrapper(self.main)
        except Exception as e:
            print("An error caused the program to crash. See radio.log for details")
            self.logger.log.exception(e)
        self.api.audioPlayer.shutdown()

    def main(self, stdscr):
        self.stdscr = stdscr
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        # Alt+key arrives as Escape followed by the key. Don't wait long to tell the two apart.
        curses.set_escdelay(25)
        stdscr.nodelay(True)
        stdscr.keypad(True)
        curses.start_color()
        self.init_styles()

        self.set_station(self.station)
        while self.running:
            self.read_keys()
            self.draw()
            time.sleep(0.05)

    def init_styles(self):
        self.styles = {}
        for pair, (name, (fg, bg)) in enumerate(STYLES.items(), start=1):
            fg_256, fg_basic, fg_bright = VGA[fg]
            bg_256, bg_basic, _ = VGA[bg]
            attr = 0
            if curses.COLORS >= 256:
                curses.init_pair(pair, fg_256, bg_256)
            elif curses.COLORS >= 16:
                curses.init_pair(pair, fg_basic + 8 if fg_bright else fg_basic, bg_basic)
            else:
                curses.init_pair(pair, fg_basic, bg_basic)
                attr = curses.A_BOLD if fg_bright else 0
            self.styles[name] = curses.color_pair(pair) | attr

    ### Input ###

    def read_keys(self):
        while True:
            try:
                key = self.stdscr.getkey()
            except curses.error:
                # No more input
                return
            if key == "\x1b":
                try:
                    next_key = self.stdscr.getkey()
                except curses.error:
                    next_key = ""
                key = f"ALT_{next_key.lower()}" if len(next_key) == 1 else "ESC"
            self.logger.log.debug(f"User pressed key {key!r}")
            self.handle_key(key)

    def handle_key(self, key):
        if key == "KEY_RESIZE":
            self.stdscr.clear()
        elif key in ("KEY_F(12)", "ALT_x"):
            self.running = False
        elif self.mode == "menu":
            self.menu_key(key)
        elif self.mode == "stations":
            self.station_dialog_key(key)
        elif self.mode == "settings":
            self.settings_dialog_key(key)
        elif self.mode == "exit":
            self.exit_dialog_key(key)
        elif self.mode == "help":
            self.help_dialog_key(key)
        elif self.mode == "about":
            if key in ENTER_KEYS + ("ESC", " ", "KEY_F(1)"):
                self.mode = "main"
        else:
            self.main_key(key)

    def main_key(self, key):
        if key.isdigit() and 1 <= int(key) <= min(9, len(self.stations)):
            self.set_station(self.stations[int(key) - 1])
        elif key == "KEY_LEFT":
            self.step_station(-1)
        elif key == "KEY_RIGHT":
            self.step_station(1)
        elif key in ("KEY_UP", "+", "="):
            self.volume_up()
        elif key in ("KEY_DOWN", "-"):
            self.volume_down()
        elif key == "v":
            self.toggle_vu_meter()
        elif key == "m":
            self.toggle_mute()
        elif key == "KEY_F(1)":
            self.open_help()
        elif key == "KEY_F(2)":
            self.open_station_dialog()
        elif key == "KEY_F(10)":
            self.open_menu(0)
        elif key == "ESC":
            self.mode = "exit"
            self.exit_yes = True
        elif key.startswith("ALT_"):
            self.open_menu_by_hotkey(key[-1])

    def menu_key(self, key):
        menus = self.menus()
        items = menus[self.menu_index][1]
        if key in ("ESC", "KEY_F(10)"):
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
        list_keys = ("KEY_UP", "KEY_DOWN", "KEY_PPAGE", "KEY_NPAGE", "KEY_HOME", "KEY_END")
        if key in list_keys or key.isdigit():
            # Picking a station puts the focus back on Play, so Enter never cancels by surprise
            self.browse_play = True
        if key in ("KEY_LEFT", "KEY_RIGHT", "\t", "KEY_BTAB"):
            self.browse_play = not self.browse_play
        elif key == "KEY_UP":
            self.dialog_sel = max(0, self.dialog_sel - 1)
        elif key == "KEY_DOWN":
            self.dialog_sel = min(last, self.dialog_sel + 1)
        elif key == "KEY_PPAGE":
            self.dialog_sel = max(0, self.dialog_sel - self.list_height)
        elif key == "KEY_NPAGE":
            self.dialog_sel = min(last, self.dialog_sel + self.list_height)
        elif key == "KEY_HOME":
            self.dialog_sel = 0
        elif key == "KEY_END":
            self.dialog_sel = last
        elif key.isdigit() and 1 <= int(key) <= len(self.stations):
            self.dialog_sel = int(key) - 1
        elif key in ENTER_KEYS and self.browse_play:
            self.logger.log.debug(f"User selected station {self.stations[self.dialog_sel]} via F2")
            self.set_station(self.stations[self.dialog_sel])
            self.mode = "main"
        elif key in ENTER_KEYS + ("ESC", "KEY_F(2)"):
            self.mode = "main"

    def settings_dialog_key(self, key):
        field = self.settings_field
        on_buttons = field in (SETTINGS_OK, SETTINGS_CANCEL)
        if key == "KEY_DOWN":
            # The buttons are one row: going down from the last field lands on OK
            self.settings_field = field if on_buttons else field + 1
        elif key == "KEY_UP":
            self.settings_field = SETTINGS_VOLUME if on_buttons else max(SETTINGS_STATION, field - 1)
        elif key in ("\t", "KEY_BTAB"):
            step = 1 if key == "\t" else -1
            self.settings_field = (field + step) % 4
        elif key in ("KEY_LEFT", "KEY_RIGHT"):
            step = -1 if key == "KEY_LEFT" else 1
            if field == SETTINGS_STATION:
                self.settings_station = (self.settings_station + step) % len(self.stations)
            elif field == SETTINGS_VOLUME:
                self.settings_volume = min(9, max(0, self.settings_volume + step))
            else:
                self.settings_field = SETTINGS_CANCEL if field == SETTINGS_OK else SETTINGS_OK
        elif key in ENTER_KEYS and field != SETTINGS_CANCEL:
            self.config.set("SETTINGS", "default_station", self.stations[self.settings_station])
            self.config.set("SETTINGS", "startup_volume", str(self.settings_volume))
            self.save_config()
            self.mode = "main"
        elif key in ENTER_KEYS + ("ESC",):
            self.mode = "main"

    def help_dialog_key(self, key):
        last = max(0, len(HELP) - self.help_height)
        if key in ("KEY_UP", "KEY_PPAGE"):
            step = 1 if key == "KEY_UP" else self.help_height
            self.help_scroll = max(0, self.help_scroll - step)
        elif key in ("KEY_DOWN", "KEY_NPAGE"):
            step = 1 if key == "KEY_DOWN" else self.help_height
            self.help_scroll = min(last, self.help_scroll + step)
        elif key in ENTER_KEYS + ("ESC", " ", "KEY_F(1)"):
            self.mode = "main"

    def exit_dialog_key(self, key):
        if key in ("KEY_LEFT", "KEY_RIGHT", "\t", "KEY_BTAB"):
            self.exit_yes = not self.exit_yes
        elif key in ("y", "Y") or (key in ENTER_KEYS and self.exit_yes):
            self.running = False
        elif key in ("n", "N", "ESC") or key in ENTER_KEYS:
            self.mode = "main"

    ### Actions ###

    def menus(self):
        # Each menu is (title, items). An item is (label, shortcut, action, checked, toggle), or None for a separator.
        # Choosing a toggle item keeps the menu open, so you can see its check mark change.
        return [
            (
                "~R~adio",
                [
                    ("~B~rowse stations...", "F2", self.open_station_dialog, False, False),
                    None,
                    ("~H~elp...", "F1", self.open_help, False, False),
                    ("~A~bout...", None, self.open_about, False, False),
                    None,
                    ("E~x~it", "Alt-X", self.quit, False, False),
                ],
            ),
            (
                "~O~ptions",
                [
                    ("~M~ute", "M", self.toggle_mute, self.muted, True),
                    None,
                    ("~V~U meter", "V", self.toggle_vu_meter, self.VU_METER, True),
                    ("~C~lock", None, self.toggle_clock, self.CLOCK, True),
                    None,
                    ("~S~ettings...", None, self.open_settings, False, False),
                ],
            ),
        ]

    def open_menu(self, index):
        self.mode = "menu"
        self.menu_index = index
        self.menu_item = 0

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

    def open_help(self):
        self.mode = "help"
        self.help_scroll = 0

    def open_station_dialog(self):
        self.mode = "stations"
        self.dialog_sel = self.stations.index(self.station)
        self.browse_play = True

    def open_settings(self):
        self.mode = "settings"
        self.settings_field = 0
        default_station = self.config["SETTINGS"]["default_station"]
        self.settings_station = self.stations.index(default_station) if default_station in self.stations else 0
        self.settings_volume = min(9, max(0, self.config.getint("SETTINGS", "startup_volume", fallback=4)))

    def quit(self):
        self.running = False

    def set_station(self, station):
        self.logger.log.debug(f"Set station => {station}")
        try:
            self.station = station
            self.api.audioPlayer.play(station)
        except Exception as e:
            self.logger.log.error(f"Failed to set station to {station}")
            self.logger.log.error(e)

    def step_station(self, step):
        index = self.stations.index(self.station) + step
        if 0 <= index < len(self.stations):
            self.set_station(self.stations[index])

    def apply_volume(self):
        self.api.audioPlayer.set_volume(0 if self.muted else self.volume)

    def volume_up(self):
        self.volume = min(9, self.volume + 1)
        self.muted = False
        self.apply_volume()

    def volume_down(self):
        self.volume = max(0, self.volume - 1)
        self.muted = False
        self.apply_volume()

    def toggle_mute(self):
        self.muted = not self.muted
        self.apply_volume()

    def toggle_vu_meter(self):
        self.VU_METER = not self.VU_METER
        self.level_meter.enabled = self.VU_METER
        self.config.set("SETTINGS", "VU_METER", f"{self.VU_METER}")
        self.save_config()

    def toggle_clock(self):
        self.CLOCK = not self.CLOCK
        self.config.set("SETTINGS", "clock", f"{self.CLOCK}")
        self.save_config()

    def save_config(self):
        with open(SETTINGS_FILE, "w") as configfile:
            self.config.write(configfile)

    def marquee(self, name, text, width):
        # Returns the part of text to show in width characters. Text that doesn't fit scrolls:
        # it rests at the start, scrolls through, and loops. A new text starts from the beginning.
        if len(text) <= width:
            return text
        now = time.time()
        if self.marquees.get(name, (None,))[0] != text:
            self.marquees[name] = (text, now)
        loop = text + MARQUEE_GAP
        cycle = MARQUEE_PAUSE + len(loop) / MARQUEE_SPEED
        elapsed = (now - self.marquees[name][1]) % cycle
        offset = max(0, int((elapsed - MARQUEE_PAUSE) * MARQUEE_SPEED))
        return (loop + loop)[offset : offset + width]

    ### Drawing primitives ###

    def put(self, y, x, text, style):
        if y < 0 or y >= self.rows or x >= self.cols:
            return
        if x < 0:
            text = text[-x:]
            x = 0
        text = text[: self.cols - x]
        try:
            self.stdscr.addstr(y, x, text, self.styles[style])
        except curses.error:
            # Accursed curses raises an error after writing the bottom right cell, but still draws it.
            pass

    def put_marked(self, y, x, text, style, hot_style):
        # Draw text with its ~hotkey~ in hot_style
        hot = False
        for part in text.split("~"):
            self.put(y, x, part, hot_style if hot else style)
            x += len(part)
            hot = not hot

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
        # A filled box with a drop shadow
        self.fill(y + 1, x + w, h, 2, "shadow")
        self.fill(y + h, x + 2, 1, w, "shadow")
        self.fill(y, x, h, w, body_style)
        self.box(y, x, h, w, border_style, double, title, title_style)

    def button(self, y, x, label, focused=False, cancel=False):
        # Cancel buttons are red, others green
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
        self.stdscr.erase()
        self.rows, self.cols = self.stdscr.getmaxyx()

        # Room for the menu bar, the main window and its shadow, and the status line
        min_rows = self.window_height() + 3
        if self.rows < min_rows or self.cols < MIN_COLS:
            self.fill(0, 0, self.rows, self.cols, "window")
            message = f"Make the terminal at least {MIN_COLS}x{min_rows}"
            self.put(self.rows // 2, max(0, (self.cols - len(message)) // 2), message, "value")
            self.stdscr.refresh()
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
        elif self.mode == "settings":
            self.draw_settings_dialog()
        elif self.mode == "exit":
            self.draw_exit_dialog()
        elif self.mode == "help":
            self.draw_help_dialog()
        self.stdscr.refresh()

    def draw_menu_bar(self):
        self.fill(0, 0, 1, self.cols, "menu")
        self.menu_x = []
        x = 2
        for i, (title, items) in enumerate(self.menus()):
            selected = self.mode == "menu" and i == self.menu_index
            style, hot_style = ("menu_sel", "menu_sel_hot") if selected else ("menu", "menu_hot")
            self.put_marked(0, x, f" {title} ", style, hot_style)
            self.menu_x.append(x)
            x += visible_len(title) + 2
        if self.CLOCK:
            clock = time.strftime("%H:%M:%S")
            self.put(0, self.cols - len(clock) - 2, clock, "menu")

    def draw_status_line(self):
        y = self.rows - 1
        self.fill(y, 0, 1, self.cols, "menu")
        x = 1
        for key, label in STATUS_HINTS[self.mode]:
            width = len(key) + 1 + len(label)
            if x + width >= self.cols:
                break
            self.put(y, x, key, "menu_hot")
            self.put(y, x + len(key) + 1, label, "menu")
            x += width + 2

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

        number = self.stations.index(self.station) + 1
        self.put(top + 2, label_x, f"Station {number}", "label")
        self.put(top + 2, value_x, self.station, "value")
        separator(top + 3)

        info = self.api.now_playing.get(self.station, {})
        self.put(top + 4, label_x, "Artist", "label")
        self.put(top + 4, value_x, self.marquee("artist", info.get("artist", ""), value_width), "value")
        self.put(top + 5, label_x, "Song", "label")
        self.put(top + 5, value_x, self.marquee("song", info.get("song", ""), value_width), "value")

        self.put(top + 6, label_x, "Played", "label")
        if self.api.audioPlayer.error:
            self.put(top + 6, value_x, " STREAM ERROR ", "error")
        elif self.api.audioPlayer.no_output or self.api.audioPlayer.stuck:
            self.put(top + 6, value_x, " NO AUDIO OUTPUT ", "error")
        elif "started_at" in info:
            seconds = max(0, int(time.time() - info["started_at"]))
            minutes, seconds = divmod(seconds, 60)
            self.put(top + 6, value_x, f"{minutes:02}:{seconds:02}", "value")
        else:
            self.put(top + 6, value_x, "--:--", "value")

        separator(top + 7)

        self.put(top + 8, label_x, "Volume", "label")
        self.put(top + 8, value_x, "◄", "label")
        self.put(top + 8, value_x + 1, "█" * self.volume, "bar_full")
        self.put(top + 8, value_x + 1 + self.volume, "░" * (9 - self.volume), "bar_empty")
        self.put(top + 8, value_x + 10, "►", "label")
        if self.muted or self.volume == 0:
            self.put(top + 8, value_x + 12, " MUTED ", "error")
        else:
            self.put(top + 8, value_x + 12, str(self.volume), "number")

        if self.VU_METER:
            self.put(top + 9, label_x, "Level", "label")
            self.draw_level_meter(top + 9, value_x, w - 18)

    def draw_level_meter(self, y, x, width):
        # Stereo LED meter. Bars show the average level, the lone lit segment is where the bar recently peaked.
        if not self.level_meter.available:
            self.put(y, x, "Needs parec and pactl", "label")
            return
        levels, peaks = self.level_meter.get()
        scale = CEILING_DB - FLOOR_DB
        for row, (channel, level, peak) in enumerate(zip("LR", levels, peaks)):
            self.put(y + row, x, channel, "label")
            lit = round((level - FLOOR_DB) / scale * width)
            hold = round((peak - FLOOR_DB) / scale * width) - 1
            for i in range(width):
                db = FLOOR_DB + (i + 1) / width * scale
                zone = "vu_high" if db > -6 else "vu_mid" if db > -12 else "vu_low"
                self.put(y + row, x + 2 + i, "■", zone if i < lit or i == hold else "vu_off")

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
        self.window(top, left, h, w, "dialog", "dialog_border", "Browse")

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

        if count > self.list_height:
            # Scroll bar on the right edge of the list
            bar_x = list_x + list_w - 1
            self.put(top + 2, bar_x, "▲", "list")
            self.put(top + 1 + self.list_height, bar_x, "▼", "list")
            track = self.list_height - 2
            if track > 0:
                self.fill(top + 3, bar_x, track, 1, "list", "░")
                thumb = round(self.dialog_sel / (count - 1) * (track - 1))
                self.put(top + 3 + thumb, bar_x, "■", "list")

        info = self.api.now_playing.get(self.stations[self.dialog_sel], {})
        info_y = top + self.list_height + 3
        self.put(info_y, left + 3, "Artist", "dialog")
        self.put(info_y, left + 11, self.marquee("browse_artist", info.get("artist", ""), w - 14), "dialog_value")
        self.put(info_y + 1, left + 3, "Song", "dialog")
        self.put(info_y + 1, left + 11, self.marquee("browse_song", info.get("song", ""), w - 14), "dialog_value")

        buttons_y = top + h - 3
        self.button(buttons_y, left + w // 2 - 12, "  Play  ", self.browse_play)
        self.button(buttons_y, left + w // 2 + 3, " Cancel ", not self.browse_play, cancel=True)

    def draw_settings_dialog(self):
        w = 44
        h = 9
        top = 1 + (self.rows - 2 - (h + 1)) // 2
        left = (self.cols - (w + 2)) // 2
        self.window(top, left, h, w, "dialog", "dialog_border", "Settings")

        volume = self.settings_volume
        fields = [
            ("Default station", f"◄ {self.stations[self.settings_station]:<11} ►"),
            ("Startup volume", f"◄ {'█' * volume}{'░' * (9 - volume)} {volume} ►"),
        ]
        for i, (label, value) in enumerate(fields):
            y = top + 2 + i * 2
            self.put(y, left + 3, label, "dialog")
            self.put(y, left + 21, f" {value} ", "list_sel" if i == self.settings_field else "list")

        buttons_y = top + h - 3
        self.button(buttons_y, left + w // 2 - 12, "   OK   ", self.settings_field == SETTINGS_OK)
        self.button(buttons_y, left + w // 2 + 3, " Cancel ", self.settings_field == SETTINGS_CANCEL, cancel=True)

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
                self.put(y, left + 5, keys, "menu_hot")
                self.put(y, left + 19, description, "dialog")

        if self.help_scroll > 0:
            self.put(top + 2, left + w - 1, "▲", "dialog_border")
        if self.help_scroll + self.help_height < len(HELP):
            self.put(top + 1 + self.help_height, left + w - 1, "▼", "dialog_border")
        self.button(top + h - 3, left + (w - 8) // 2, "   OK   ", True)

    def draw_exit_dialog(self):
        w = 34
        h = 8
        top = 1 + (self.rows - 2 - (h + 1)) // 2
        left = (self.cols - (w + 2)) // 2
        self.window(top, left, h, w, "dialog", "dialog_border", "Exit")

        question = "Quit Nightride FM?"
        self.put(top + 2, left + (w - len(question)) // 2, question, "dialog")
        buttons_y = top + h - 3
        self.button(buttons_y, left + w // 2 - 11, "  Yes   ", self.exit_yes)
        self.button(buttons_y, left + w // 2 + 2, "   No   ", not self.exit_yes, cancel=True)

    def draw_about_dialog(self):
        w = 44
        h = 13
        top = 1 + (self.rows - 2 - (h + 1)) // 2
        left = (self.cols - (w + 2)) // 2
        self.window(top, left, h, w, "dialog", "dialog_border", "About")

        def centered(y, text, style):
            self.put(y, left + (w - len(text)) // 2, text, style)

        centered(top + 2, "NIGHTRIDE.FM", "dialog_value")
        centered(top + 3, "Player for Nightride.fm", "dialog")
        centered(top + 4, f"Version {self.version}", "dialog")
        centered(top + 6, "Matias Räisänen 2026", "dialog")
        centered(top + 7, "matias@matiasraisanen.com", "dialog_value")
        centered(top + 8, "github.com/matiasraisanen/nightride", "dialog_value")
        self.button(top + 10, left + (w - 8) // 2, "   OK   ")


if __name__ == "__main__":
    radio = RadioInterface(loglevel=logging.INFO)
