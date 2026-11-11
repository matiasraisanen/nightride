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
    },
    "STATIONS": {
        "1": "nightride",
        "2": "chillsynth",
        "3": "darksynth",
        "4": "horrorsynth",
        "5": "spacesynth",
        "6": "datawave",
        "7": "ebsm",
        "8": "rektory",
        "9": "rekt",
    },
    "SETTINGS": {
        "vu_meter": "False",
        "default_station": "chillsynth",
        "startup_volume": "4",
        "clock": "True",
        "theme": "Synthwave",
    },
}

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
    config = configparser.ConfigParser()
    try:
        config.read(SETTINGS_FILE)
    except configparser.Error as e:
        log().warning(f"Could not read {SETTINGS_FILE}, using default settings: {e}")
        config = configparser.ConfigParser()

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
