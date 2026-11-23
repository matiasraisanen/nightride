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
# The song info comes a few seconds before the song starts in the audio stream. The player measures
# that gap this often, on the next song change, from the song titles inside the audio stream.
GAP_MEASURE_SECONDS = 30 * 60
# After a failed measurement, try again on a song change after this long
GAP_RETRY_SECONDS = 2 * 60
# A measured gap outside this is wrong
MAX_GAP_SECONDS = 15
# Song info events this soon after connecting are the songs already playing, not changes
CONNECT_DUMP_SECONDS = 3
# Measuring reads the audio stream at least this long, to see how much past audio the server sent
GAP_SETTLE_SECONDS = 4
# and gives up if the title hasn't changed by then
GAP_TIMEOUT_SECONDS = 30
# The audio between song titles in the stream is this many bytes at most. Icecast uses 16000.
MAX_METAINT = 64 * 1024


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
        self.audio_base_url = AUDIO_STREAM_BASE_URL
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
        self.connected_at = None
        self.disconnected_since = time.time()
        # Seconds from a song's start time in the song info to its start in the live audio stream,
        # or None if not measured yet. The last measurement is kept in the settings.
        try:
            self.gap = float(config["SETTINGS"].get("sync_gap", ""))
        except ValueError:
            self.gap = None
        # Why the gap can't be measured, or None
        self.gap_problem = None
        # When the gap was last measured (time.time()), or None
        self.gap_measured_at = None
        # When to measure next (monotonic), and whether a measurement is running
        self.gap_next = 0
        self.gap_measuring = False
        # Station => what its stream server says about it, see check_stream_format
        self.stream_format = {}

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
                    self.connected_at = time.monotonic()
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
            if time.monotonic() - self.connected_at > CONNECT_DUMP_SECONDS:
                self.maybe_measure_gap(station, start_time)
        self.logger.log.debug(f"New song detected on {station}: {artist} - {title}")


    def maybe_measure_gap(self, station, start_time):
        # A song just changed. Time when it starts in the audio stream, if it's time to.
        if self.gap_measuring or time.monotonic() < self.gap_next:
            return
        self.gap_measuring = True
        thread = threading.Thread(target=self.measure_gap, args=(station, start_time), daemon=True)
        thread.start()

    def measure_gap(self, station, start_time):
        try:
            gap = self.read_gap(station, start_time)
        except Exception as e:
            self.logger.log.warning(f"Could not measure when songs start in the audio stream: {e}")
            self.gap_next = time.monotonic() + GAP_RETRY_SECONDS
            return
        finally:
            self.gap_measuring = False
        self.gap_next = time.monotonic() + GAP_MEASURE_SECONDS
        if not 0 <= gap <= MAX_GAP_SECONDS:
            problem = f"songs would start {gap:.1f} seconds after the song info, which can't be right"
            if problem != self.gap_problem:
                self.logger.log.warning(f"Song info can't be synced with the audio: {problem}")
            self.gap_problem = problem
            # It may have been a one-off, so check again soon
            self.gap_next = time.monotonic() + GAP_RETRY_SECONDS
            return
        if self.gap is None or abs(gap - self.gap) > 1:
            before = "" if self.gap is None else f", was {self.gap:.1f}"
            self.logger.log.info(f"Songs start in the audio stream {gap:.1f} seconds after the song info{before}")
        else:
            self.logger.log.debug(f"Songs start in the audio stream {gap:.1f} seconds after the song info")
        if self.gap_problem:
            self.logger.log.info("Song info is synced with the audio again")
        self.gap_problem = None
        self.gap = gap
        self.gap_measured_at = time.time()

    def read_gap(self, station, start_time):
        # Reads the station's audio stream with the song titles in it (Icecast's ICY metadata,
        # which VLC doesn't pass on), and finds where the title changes. The server first sends
        # some seconds of past audio, then the rest as it plays live, so a position in the stream
        # tells when that audio was live.
        http = urllib3.PoolManager(
            timeout=urllib3.Timeout(connect=CONNECT_TIMEOUT_SECONDS, read=10), retries=False
        )
        response = http.request(
            "GET", f"{self.audio_base_url}/{station}.mp3", preload_content=False, headers={"Icy-MetaData": "1"}
        )
        connected = time.time()
        try:
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status}")
            metaint = int(response.headers["icy-metaint"])
            if not 0 < metaint <= MAX_METAINT:
                raise RuntimeError(f"the stream says its song titles are {metaint} bytes apart, which can't be right")
            # Bytes a second
            rate = int(response.headers["icy-br"].split(",")[0]) * 1000 / 8
            audio = 0
            first_title = changed_at = burst = None

            def read(size, keep=True):
                # size bytes from the stream, or none kept if keep is false. Gives up at the deadline
                # even when the data keeps coming slowly.
                data = b""
                left = size
                while left:
                    if time.time() - connected > GAP_TIMEOUT_SECONDS:
                        raise RuntimeError(f"the song title in the audio stream didn't change in {GAP_TIMEOUT_SECONDS} seconds")
                    chunk = response.read(min(left, 4096))
                    if not chunk:
                        raise RuntimeError("the stream ended")
                    left -= len(chunk)
                    if keep:
                        data += chunk
                return data

            while True:
                read(metaint, keep=False)
                audio += metaint
                elapsed = time.time() - connected
                if burst is None and elapsed >= GAP_SETTLE_SECONDS:
                    # The audio received beyond real time is the past audio sent first
                    burst = audio - rate * elapsed
                if changed_at is not None and burst is not None:
                    break
                if elapsed > GAP_TIMEOUT_SECONDS:
                    raise RuntimeError(f"the song title in the audio stream didn't change in {GAP_TIMEOUT_SECONDS} seconds")
                length = read(1)[0] * 16
                if not length:
                    continue
                title = read(length).rstrip(b"\0").decode("utf-8", "replace")
                if first_title is None:
                    first_title = title
                elif title != first_title and changed_at is None:
                    changed_at = audio
        finally:
            response.release_conn()
        # When the audio at the title change was live
        live = connected + (changed_at - burst) / rate
        return live - start_time

    def check_stream_format(self, station):
        # For Help > Stream info: what the stream server says about the station's stream, from
        # the headers it sends before the audio. Read in the background into stream_format.
        self.stream_format[station] = None
        threading.Thread(target=self.read_stream_format, args=(station,), daemon=True).start()

    def read_stream_format(self, station):
        http = urllib3.PoolManager(
            timeout=urllib3.Timeout(connect=CONNECT_TIMEOUT_SECONDS, read=CONNECT_TIMEOUT_SECONDS), retries=False
        )
        try:
            response = http.request("GET", f"{self.audio_base_url}/{station}.mp3", preload_content=False)
            # Only the headers are needed, so the audio after them isn't read
            response.close()
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status}")
        except Exception as e:
            self.logger.log.warning(f"Could not check the stream format of {station}: {e}")
            self.stream_format[station] = {"error": str(e)}
            return
        headers = response.headers
        # Like "channels=2;samplerate=44100;bitrate=320"
        info = dict(
            part.split("=", 1) for part in headers.get("ice-audio-info", "").split(";") if "=" in part
        )
        # Shown on the screen, so without control characters that could change the terminal
        self.stream_format[station] = {
            "type": clean(headers.get("content-type", "")),
            "kbits": clean(info.get("bitrate") or headers.get("icy-br", "").split(",")[0]),
            "samplerate": clean(info.get("samplerate", "")),
            "channels": clean(info.get("channels", "")),
        }

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
