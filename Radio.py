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
    "button_shadow": ("black", "lightgray"),
    "shadow": ("darkgray", "black"),
}

# Key hints on the bottom status line, per screen
STATUS_HINTS = {
    "main": [
        ("F1", "About"),
        ("F2", "Stations"),
        ("F10", "Menu"),
        ("←→", "Station"),
        ("-+", "Volume"),
        ("Alt-X", "Exit"),
    ],
    "menu": [("←→", "Menus"), ("↑↓", "Select"), ("Enter", "Choose"), ("Esc", "Close")],
    "stations": [("↑↓", "Move"), ("Enter", "Play"), ("Esc", "Cancel")],
    "about": [("Enter", "Close")],
}

ENTER_KEYS = ("\n", "\r", "KEY_ENTER")

MIN_COLS = 50


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
        self.volume = 4
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
        self.list_height = 1
        self.menu_x = []

        try:
            curses.wrapper(self.main)
        except Exception as e:
            print("An error caused the program to crash. See radio.log for details")
            self.logger.log.exception(e)
        self.api.audioPlayer.stop()

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
        elif key in ("+", "="):
            self.volume_up()
        elif key == "-":
            self.volume_down()
        elif key == "v":
            self.toggle_vu_meter()
        elif key == "m":
            self.toggle_mute()
        elif key == "KEY_F(1)":
            self.open_about()
        elif key == "KEY_F(2)":
            self.open_station_dialog()
        elif key == "KEY_F(10)":
            self.open_menu(0)
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
            for item in items:
                if item is not None and hotkey(item[0]) == key.lower():
                    self.run_menu_item(item)
                    break

    def station_dialog_key(self, key):
        last = len(self.stations) - 1
        if key == "KEY_UP":
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
        elif key in ENTER_KEYS:
            self.logger.log.debug(f"User selected station {self.stations[self.dialog_sel]} via F2")
            self.set_station(self.stations[self.dialog_sel])
            self.mode = "main"
        elif key in ("ESC", "KEY_F(2)"):
            self.mode = "main"

    ### Actions ###

    def menus(self):
        # Each menu is (title, items). An item is (label, shortcut, action, checked), or None for a separator.
        station_items = []
        for i, station in enumerate(self.stations):
            label = f"~{i + 1}~ {station}" if i < 9 else f"   {station}"
            station_items.append(
                (label, None, lambda s=station: self.set_station(s), station == self.station)
            )
        station_items += [None, ("~B~rowse...", "F2", self.open_station_dialog, False)]

        return [
            (
                "~R~adio",
                [
                    ("~M~ute", "M", self.toggle_mute, self.muted),
                    None,
                    ("E~x~it", "Alt-X", self.quit, False),
                ],
            ),
            ("~S~tation", station_items),
            (
                "~O~ptions",
                [
                    ("Volume ~u~p", "+", self.volume_up, False),
                    ("Volume ~d~own", "-", self.volume_down, False),
                    None,
                    ("~V~U meter", "V", self.toggle_vu_meter, self.VU_METER),
                ],
            ),
            ("~H~elp", [("~A~bout...", "F1", self.open_about, False)]),
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
        label, shortcut, action, checked = item
        self.mode = "main"
        action()

    def open_about(self):
        self.mode = "about"

    def open_station_dialog(self):
        self.mode = "stations"
        self.dialog_sel = self.stations.index(self.station)

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

    def save_config(self):
        with open(SETTINGS_FILE, "w") as configfile:
            self.config.write(configfile)

    def shorten(self, word, max_length=29):
        if len(word) > max_length:
            word = word[: max_length - 3] + "..."
        return word

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

    def button(self, y, x, label):
        self.put(y, x, label, "button")
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
        self.put(top + 2, label_x, "Station", "label")
        self.put(top + 2, value_x, str(number), "number")
        self.put(top + 2, value_x + 3, self.station, "value")
        separator(top + 3)

        info = self.api.now_playing.get(self.station, {})
        self.put(top + 4, label_x, "Artist", "label")
        self.put(top + 4, value_x, self.shorten(info.get("artist", ""), value_width), "value")
        self.put(top + 5, label_x, "Song", "label")
        self.put(top + 5, value_x, self.shorten(info.get("song", ""), value_width), "value")

        self.put(top + 6, label_x, "Played", "label")
        if self.api.audioPlayer.error:
            self.put(top + 6, value_x, " STREAM ERROR ", "error")
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
        if self.muted:
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
            label, shortcut, action, checked = item
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
        self.put(info_y, left + 11, self.shorten(info.get("artist", ""), w - 14), "dialog_value")
        self.put(info_y + 1, left + 3, "Song", "dialog")
        self.put(info_y + 1, left + 11, self.shorten(info.get("song", ""), w - 14), "dialog_value")

        buttons_y = top + h - 3
        self.button(buttons_y, left + w // 2 - 12, "   OK   ")
        self.button(buttons_y, left + w // 2 + 3, " Cancel ")

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
