import collections
import json
import logging
import os
import re
import sseclient
import urllib3
import time
import threading
import settings
from logger import Logger
from paths import HISTORY_FILE, LOG_FILE

from audio_player import AudioPlayer

# The server sends a keepalive event every 20 seconds or so. This long without any data means the
# connection has silently dropped.
READ_TIMEOUT_SECONDS = 90
CONNECT_TIMEOUT_SECONDS = 10
# Seconds to wait before each reconnect attempt. The last one repeats.
RETRY_DELAYS = [2, 5, 10, 30]
# Songs remembered per station for "Recently played"
HISTORY_LENGTH = 20
# Songs older than this are dropped from the saved history, so after a restart the list starts
# from about the last hour
HISTORY_KEEP_SECONDS = 60 * 60


def clean(text):
    # Control characters (newlines, tabs, null bytes) in a title would break the layout
    return "".join(c if c.isprintable() else " " for c in str(text)).strip()


class NightRideAPI:
    def __init__(self, loglevel=logging.INFO, logfile: str = LOG_FILE):
        self.logger = Logger(
            module_name=__name__,
            log_file=logfile,
            log_level=loglevel,
            streamhandler=False,
            filehandler=True,
        )

        ### Read config ###
        config = settings.load()
        self.SSE_URL = config["URLS"]["sse_url"]
        AUDIO_STREAM_BASE_URL = config["URLS"]["audio_stream_base_url"]
        self.stations = [value for key, value in config.items("STATIONS")]

        # Initialize audio player
        self.audioPlayer = AudioPlayer(
            base_url=AUDIO_STREAM_BASE_URL, loglevel=loglevel, logfile=logfile
        )

        for x in self.stations:
            self.logger.log.debug(f"Station {self.stations.index(x)}: {x}")

        # Station => {"artist", "song", "started_at"}
        self.now_playing = {}
        # Station => the songs played since the player started, newest last, as now_playing has them
        self.history = collections.defaultdict(lambda: collections.deque(maxlen=HISTORY_LENGTH))
        self.load_history()
        # Whether the metadata stream is connected, and since when it hasn't been
        self.connected = False
        self.disconnected_since = time.time()

        # Connecting happens in the background, so the interface can start right away
        thread_1 = threading.Thread(target=self.run)
        thread_1.daemon = True
        thread_1.start()

    def run(self):
        # Keep the metadata stream connected, reconnecting whenever it drops or fails
        attempts = 0
        while True:
            try:
                self.listen()
                self.logger.log.warning("Metadata stream ended")
            except Exception as e:
                self.logger.log.warning(f"Metadata stream failed: {e}")
            if self.connected:
                # It was working, so start the retry delays from the beginning
                attempts = 0
                self.connected = False
                self.disconnected_since = time.time()
            delay = RETRY_DELAYS[min(attempts, len(RETRY_DELAYS) - 1)]
            attempts += 1
            self.logger.log.info(f"Reconnecting to the metadata stream in {delay} seconds")
            time.sleep(delay)

    def listen(self):
        self.logger.log.debug(f"Start SSE client")
        http = urllib3.PoolManager(
            timeout=urllib3.Timeout(connect=CONNECT_TIMEOUT_SECONDS, read=READ_TIMEOUT_SECONDS),
            retries=False,
        )
        response = http.request(
            "GET", self.SSE_URL, preload_content=False, headers={"Accept": "text/event-stream"}
        )
        try:
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status}")
            for event in sseclient.SSEClient(response).events():
                self.logger.log.debug(f"SSE event received: {event.data}")
                if not self.connected:
                    self.logger.log.info("Metadata stream connected")
                    self.connected = True
                if event.data == "keepalive":
                    continue
                try:
                    self.handle_event(event.data)
                except (ValueError, KeyError, IndexError, TypeError, AttributeError) as e:
                    # One odd event shouldn't stop the updates
                    self.logger.log.warning(f"Skipping metadata event {event.data!r}: {e}")
        finally:
            response.release_conn()

    def handle_event(self, data):
        data = json.loads(data)
        station = data[0]["station"]

        # Event can contain undefined values. We need to turn them into empty strings.
        artist = clean(data[0].get("artist") or "")
        title = clean(data[0].get("title") or "")

        if not artist:
            # Some tracks only have "Artist - Title" in the title field.
            pattern = r"(.+)\s-\s(.+)"
            match = re.search(pattern, title)
            if match:
                artist = match.group(1)
                title = match.group(2)

        # 'at' is the song's start time as a unix timestamp in milliseconds.
        # Fall back to the time the event was received.
        if data[0].get("at"):
            start_time = data[0]["at"] / 1000
        else:
            start_time = time.time()

        song = {
            "artist": artist,
            "song": title,
            "started_at": start_time,
        }
        self.now_playing[station] = song
        # The same song can be sent again, e.g. after reconnecting
        history = self.history[station]
        if not history or (history[-1]["artist"], history[-1]["song"]) != (artist, title):
            history.append(song)
            self.save_history()
        self.logger.log.debug(f"New song detected on {station}: {artist} - {title}")


    def load_history(self):
        # The songs saved by the last run, if they are recent enough
        try:
            with open(HISTORY_FILE, encoding="utf-8") as f:
                saved = json.load(f)
            cutoff = time.time() - HISTORY_KEEP_SECONDS
            for station, songs in saved.items():
                for song in songs:
                    if song["started_at"] >= cutoff:
                        self.history[station].append(
                            {
                                "artist": str(song["artist"]),
                                "song": str(song["song"]),
                                "started_at": float(song["started_at"]),
                            }
                        )
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
            self.logger.log.warning(f"Could not read the song history from {HISTORY_FILE}: {e}")

    def save_history(self):
        # Write a new file and swap it in, so the player stopping halfway can't leave it broken
        cutoff = time.time() - HISTORY_KEEP_SECONDS
        recent = {
            station: [song for song in songs if song["started_at"] >= cutoff]
            for station, songs in list(self.history.items())
        }
        temp_file = HISTORY_FILE + ".tmp"
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump({station: songs for station, songs in recent.items() if songs}, f, ensure_ascii=False)
            os.replace(temp_file, HISTORY_FILE)
        except OSError as e:
            self.logger.log.warning(f"Could not save the song history to {HISTORY_FILE}: {e}")


if __name__ == "__main__":
    nightRide = NightRideAPI(loglevel=logging.DEBUG)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        nightRide.audioPlayer.shutdown()
