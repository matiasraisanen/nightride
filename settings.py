import configparser
import os
import shutil
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
        # strftime formats, see https://strftime.org
        "clock_format": "%H:%M",
        "date_format": "%d.%m.%Y",
        # Messages above the status line: all, off, or a list of songs (new songs) and actions (what a
        # key did), such as "songs, actions". Errors always show.
        "notifications": "all",
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


def get_bool(config, section, key):
    # A yes/no setting. Falls back to the default if it can't be read as one.
    try:
        return config.getboolean(section, key)
    except ValueError:
        log().warning(f"Setting {key} = {config.get(section, key)!r} is not true or false, using the default")
        return DEFAULTS[section][key] == "True"
