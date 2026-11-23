import configparser
import os
import re
import shutil
import time
from logger import Logger
from paths import DEFAULT_SETTINGS_FILE, LOG_FILE, SETTINGS_FILE

# Used for anything missing from settings.ini, so a broken or partial file can't stop the player
DEFAULTS = {
    "URLS": {
        "sse_url": "https://nightride.fm/meta",
        "audio_stream_base_url": "https://stream.nightride.fm",
        # Opened from Help > Nightride.fm on web
        "website": "https://nightride.fm",
        # Web search. {query} is replaced with the song's artist and title.
        "bandcamp_search": "https://bandcamp.com/search?q={query}",
        "youtube_search": "https://www.youtube.com/results?search_query={query}",
        "google_search": "https://www.google.com/search?q={query}",
    },
    # The stations nightride.fm lists, in its order
    "STATIONS": {
        "1": "nightride",
        "2": "chillsynth",
        "3": "datawave",
        "4": "spacesynth",
        "5": "darksynth",
        "6": "horrorsynth",
        "7": "ebsm",
    },
    "SETTINGS": {
        "vu_meter": "True",
        # A station's name, or "last" for the one played last
        "default_station": "last",
        "last_station": "chillsynth",
        # 0 to 99, or "last" for the volume used last
        "start_volume": "last",
        "last_volume": "40",
        # Clicks and the scroll wheel. Off leaves the mouse to the terminal, for selecting text.
        "mouse": "True",
        "clock": "True",
        "date": "True",
        # The clock and date formats in use, and the ones Settings cycles through: strftime formats,
        # see https://strftime.org. The lists are one format per line, indented.
        "clock_format": "%H:%M",
        "clock_formats": "\n%H:%M\n%H:%M:%S\n%I:%M %p",
        "date_format": "%d.%m.%Y",
        "date_formats": "\n%d.%m.%Y\n%a %d.%m.\n%Y-%m-%d\n%a %d %b",
        # Messages above the status line: all, off, or a list of songs (new songs), actions (what a
        # key did) and errors, such as "songs, errors"
        "notifications": "all",
        # Show a song when it starts in the audio, not when the song info says it started, which is
        # some seconds earlier
        "sync_song_info": "True",
        # Measured by the player: seconds from a song's start in the song info to its start in the
        # audio stream, and how far the audio heard is behind the live stream
        "sync_gap": "",
        "sync_lag": "",
        "theme": "Synthwave",
    },
}

# The station list that came with older versions. A settings file that still has it gets the new
# one, while a list the user has changed is kept.
OLD_DEFAULT_STATIONS = [
    "nightride", "chillsynth", "darksynth", "horrorsynth", "spacesynth", "datawave", "ebsm", "rektory", "rekt"
]

_logger = None


def log():
    # Created on first use, after the main module has cleared the old log file
    global _logger
    if _logger is None:
        _logger = Logger(module_name=__name__, log_file=LOG_FILE, filehandler=True).log
    return _logger


def load():
    # Reads settings.ini, filling in anything missing from DEFAULTS
    if not os.path.exists(SETTINGS_FILE) and os.path.exists(DEFAULT_SETTINGS_FILE):
        # First start: begin with the settings that come with the code
        try:
            shutil.copyfile(DEFAULT_SETTINGS_FILE, SETTINGS_FILE)
        except OSError as e:
            log().warning(f"Could not copy {DEFAULT_SETTINGS_FILE} to {SETTINGS_FILE}: {e}")
    config = configparser.ConfigParser(interpolation=None)
    try:
        config.read(SETTINGS_FILE)
    except configparser.Error as e:
        log().warning(f"Could not read {SETTINGS_FILE}, using default settings: {e}")
        config = configparser.ConfigParser(interpolation=None)

    if config.has_section("STATIONS") and [v for _, v in config.items("STATIONS")] == OLD_DEFAULT_STATIONS:
        log().info("Updating the station list to the one nightride.fm has now")
        # Emptied rather than removed, so the section keeps its place in the file
        for key in config.options("STATIONS"):
            config.remove_option("STATIONS", key)

    # The startup volume used to be 0 to 9, and was played at 11 times that. Now it is 0 to 99, and
    # by default the last used one. The old one becomes the last used one, so the first start after
    # the update sounds the same.
    if config.has_option("SETTINGS", "startup_volume"):
        if not config.has_option("SETTINGS", "last_volume"):
            try:
                old = min(9, max(0, config.getint("SETTINGS", "startup_volume")))
                config.set("SETTINGS", "last_volume", str(old * 11))
                log().info(f"Startup volume {old} is now the last used volume {old * 11}, on the new 0 to 99 scale")
            except ValueError:
                pass
        config.remove_option("SETTINGS", "startup_volume")

    # Before "last played" existed, chillsynth was the default and there was no last_station. Such a
    # file gets the new default.
    if (
        config.has_section("SETTINGS")
        and config.get("SETTINGS", "default_station", fallback=None) == "chillsynth"
        and not config.has_option("SETTINGS", "last_station")
    ):
        log().info("Starting on the last played station, the new default")
        config.set("SETTINGS", "default_station", "last")

    # Before the format lists, Settings had fixed formats, and a format written by hand was lost
    # when another one was chosen. Such a format goes first in the new list.
    for kind in ("clock", "date"):
        current = config.get("SETTINGS", f"{kind}_format", fallback=None)
        defaults = parse_list(DEFAULTS["SETTINGS"][f"{kind}_formats"])
        if current and not config.has_option("SETTINGS", f"{kind}_formats") and current not in defaults:
            log().info(f"Adding the {kind} format {current!r} to the list of {kind} formats")
            config.set("SETTINGS", f"{kind}_formats", "\n".join([""] + [current] + defaults))

    # Errors used to always show, so a file from before they could be turned off gets them on
    if config.has_option("SETTINGS", "notifications") and not config.has_option("SETTINGS", "sync_song_info"):
        value = config.get("SETTINGS", "notifications").strip()
        if value.lower() in ("off", "none", ""):
            config.set("SETTINGS", "notifications", "errors")
        elif value.lower() != "all" and "errors" not in value.lower():
            config.set("SETTINGS", "notifications", f"{value}, errors")

    for section, values in DEFAULTS.items():
        if not config.has_section(section):
            config.add_section(section)
        if section == "STATIONS":
            # The station list is used as a whole: defaults only if the file has none
            if not config.items("STATIONS"):
                config.read_dict({"STATIONS": values})
            continue
        for key, value in values.items():
            if not config.has_option(section, key):
                config.set(section, key, value)
    return config


def save(config):
    # Write a new file and swap it in, so a crash halfway through can't leave settings.ini broken
    temp_file = SETTINGS_FILE + ".tmp"
    with open(temp_file, "w") as configfile:
        config.write(configfile)
    os.replace(temp_file, SETTINGS_FILE)


def get_int(config, section, key, low, high):
    # An integer setting, clamped to low..high. Falls back to the default if it isn't a number.
    try:
        value = config.getint(section, key)
    except ValueError:
        log().warning(f"Setting {key} = {config.get(section, key)!r} is not a number, using the default")
        value = int(DEFAULTS[section][key])
    return min(high, max(low, value))


def parse_list(value):
    # A setting with one value per line
    return [line.strip() for line in value.splitlines() if line.strip()]


def get_list(config, section, key):
    return parse_list(config.get(section, key))


# Clock and date texts longer than this don't fit next to the menus
MAX_FORMAT_LENGTH = 30


def format_problem(fmt):
    # What is wrong with a strftime format for the clock or date, or None if nothing. Python passes
    # the format to the system: on Linux an unknown code shows as it is, on Windows it fails.
    if not fmt:
        return "is empty"
    if not fmt.isprintable():
        return "has control characters"
    i = 0
    while True:
        i = fmt.find("%", i)
        if i < 0:
            break
        # A code is %, then flags and a width that some systems allow (like %-d), then a letter
        match = re.match(r"%[-_0^#]*\d*[EO]?(.)", fmt[i:])
        if not match:
            return "ends with a lone %"
        code = match.group(0)
        if code != "%%":
            try:
                if time.strftime(code) == code:
                    return f"has an unknown code {code}"
            except ValueError:
                return f"has a code {code} that this system doesn't know"
        i += len(code)
    try:
        text = time.strftime(fmt)
    except ValueError as e:
        return f"is not valid: {e}"
    if len(text) > MAX_FORMAT_LENGTH:
        return f"is too long, over {MAX_FORMAT_LENGTH} characters"
    return None


def get_bool(config, section, key):
    # A yes/no setting. Falls back to the default if it can't be read as one.
    try:
        return config.getboolean(section, key)
    except ValueError:
        log().warning(f"Setting {key} = {config.get(section, key)!r} is not true or false, using the default")
        return DEFAULTS[section][key] == "True"
