import os

# Resolve files relative to this script, so the player can be started from any directory.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.ini")
LOG_FILE = os.path.join(BASE_DIR, "radio.log")
