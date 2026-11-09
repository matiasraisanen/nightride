import json
import math
import os
import shutil
import subprocess


def parse_db(text):
    # pactl reports volumes like "-39.45 dB" or "-inf dB"
    return float(text.split()[0])


def available():
    return bool(shutil.which("pactl"))


def find_own_stream():
    # Returns (sink input index, volume in dB) of this process's playback stream in PulseAudio
    # (or PipeWire's PulseAudio layer), or None if it has none.
    # Raises OSError, subprocess.SubprocessError or ValueError if the streams can't be listed.
    result = subprocess.run(
        ["pactl", "-f", "json", "list", "sink-inputs"],
        capture_output=True,
        text=True,
        timeout=2,
    )
    streams = json.loads(result.stdout)

    mine = [
        stream
        for stream in streams
        if stream["properties"].get("application.process.id") == str(os.getpid())
    ]
    if not mine:
        return None
    # When switching stations there may briefly be two. The newest one is playing.
    stream = max(mine, key=lambda s: s["index"])
    gain_db = min(parse_db(channel["db"]) for channel in stream["volume"].values())
    if stream["mute"]:
        gain_db = -math.inf
    return stream["index"], gain_db
