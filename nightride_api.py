import collections
import datetime
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
# Songs remembered per station, kept across restarts, plus the jingles between them. Recently played
# shows 10, and the newest may not be heard yet when the song info is ahead of the audio.
HISTORY_SONGS = 12
# Recently played covers one listening session, however long, also past midnight. After a break
# this long without song info (the player closed, the computer asleep or offline) it starts afresh.
# A quick restart keeps it.
LISTENING_BREAK_SECONDS = 2 * 60 * 60
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
# Each station also has an HLS stream: the audio in 4-second pieces, each tagged with the song
# playing, its Spotify ID included. A new song's pieces show up in the list some 15 seconds after
# the song info. Looking for them stops after this long.
SPOTIFY_TIMEOUT_SECONDS = 90
SPOTIFY_POLL_SECONDS = 4
# The tags are at the start of a piece, in its first 300 bytes or so
TAG_BYTES = 4096
# Spotify track IDs are 22 letters and digits
SPOTIFY_ID = re.compile(rb"(?<![0-9A-Za-z])[0-9A-Za-z]{22}(?![0-9A-Za-z])")


def clean(text):
    # Control characters (newlines, tabs, null bytes) in a title would break the layout
    return "".join(c if c.isprintable() else " " for c in str(text)).strip()


def song_kind(song):
    # "jingle" for the station's jingles, read by an artist: "Nightride FM (Jingle)".
    # "live" for live shows: "The State of Synth Live - Live on nightride".
    # "song" for everything else.
    title = song.get("song", "")
    if re.search(r"\(jingle\)", title, re.IGNORECASE):
        return "jingle"
    if re.match(r"live on\b", title, re.IGNORECASE):
        return "live"
    return "song"


def trim_history(songs):
    # Drops the oldest entries of a station's history until it has HISTORY_SONGS songs. Jingles
    # don't count, so the ones between the songs kept stay.
    while sum(song_kind(song) != "jingle" for song in songs) > HISTORY_SONGS:
        songs.popleft()


def jingle_title(title):
    # A jingle's title without the "(Jingle)" mark
    return re.sub(r"\s*\(jingle\)", "", title, flags=re.IGNORECASE).strip()


def read_id3(data):
    # The text frames of the ID3v2.3 tag at the start of data: {frame id: bytes after the encoding byte}
    if data[:3] != b"ID3":
        return {}
    end = 10 + sum(b << (7 * (3 - i)) for i, b in enumerate(data[6:10]))
    pos, frames = 10, {}
    while pos + 10 <= min(end, len(data)) and data[pos:pos + 4].strip(b"\0"):
        frame_id = data[pos:pos + 4].decode("latin1")
        size = int.from_bytes(data[pos + 4:pos + 8], "big")
        frames[frame_id] = data[pos + 10:pos + 10 + size]
        pos += 10 + size
    return frames


def id3_text(body):
    encoding = {0: "latin1", 1: "utf-16", 2: "utf-16-be"}.get(body[:1][0] if body else 3, "utf-8")
    return clean(body[1:].decode(encoding, "replace").strip("\0"))


def parse_pdt(text):
    # A program date time like 2026-11-25T08:28:17.866Z, as a unix timestamp
    text = text.strip().replace("Z", "+00:00")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.datetime.strptime(text, fmt).timestamp()
        except ValueError:
            pass
    raise ValueError(f"unknown time {text!r}")


def same_song(tags, song):
    # Whether a piece's tags are for song. The song info may have the artist in the title.
    def norm(text):
        return " ".join(text.lower().split())

    artist, title = id3_text(tags.get("TPE1", b"")), id3_text(tags.get("TIT2", b""))
    tagged = {norm(title), norm(f"{artist} - {title}")}
    known = {norm(song["song"]), norm(f"{song['artist']} - {song['song']}")}
    return bool(tagged & known - {"", "-"})


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
        # Station => the songs played since the player started, newest last, as now_playing has them.
        # A song can also have "spotify", its Spotify track ID, found a little after it starts.
        self.history = collections.defaultdict(collections.deque)
        # The history is added to by the metadata thread and the Spotify lookups, and saved by both
        self.history_lock = threading.RLock()
        # When song info last came (time.time()), also a keepalive, or None. For finding listening breaks.
        self.last_heard = None
        self.load_history()
        # Songs whose Spotify ID has been looked for: (station, started_at, artist, title)
        self.spotify_lookups = set()
        # For reading the tags in the HLS streams
        self.tag_http = urllib3.PoolManager(
            timeout=urllib3.Timeout(connect=CONNECT_TIMEOUT_SECONDS, read=CONNECT_TIMEOUT_SECONDS), retries=False
        )
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
                self.check_break()
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
        # The same song can be sent again, e.g. after reconnecting
        with self.history_lock:
            history = self.history[station]
            if history and (history[-1]["artist"], history[-1]["song"]) == (artist, title):
                # Keep what is known about it, like its Spotify ID
                song = history[-1]
                new = False
            else:
                history.append(song)
                trim_history(history)
                self.save_history()
                new = True
        self.now_playing[station] = song
        if new and time.monotonic() - self.connected_at > CONNECT_DUMP_SECONDS:
            self.maybe_measure_gap(station, start_time)
        # Once per song. A song from the saved history may still be playing and not have its ID yet.
        lookup = (station, song["started_at"], artist, title)
        if song_kind(song) == "song" and "spotify" not in song and lookup not in self.spotify_lookups:
            self.spotify_lookups.add(lookup)
            threading.Thread(target=self.find_spotify_id, args=(station, song), daemon=True).start()
        self.logger.log.debug(f"New song detected on {station}: {artist} - {title}")

    def find_spotify_id(self, station, song):
        # Reads the song's Spotify ID from the tags in the station's HLS stream, into song["spotify"].
        # Leaves it out if the song's pieces don't have one or can't be found.
        deadline = time.time() + SPOTIFY_TIMEOUT_SECONDS
        checked = set()
        while time.time() < deadline:
            try:
                pieces = self.hls_pieces(station)
                if pieces and pieces[0][0] > song["started_at"] + 1:
                    # It started before the oldest piece listed, so only the newest can still be it
                    candidates = pieces[-1:]
                else:
                    # Pieces start where songs do, and their times match the song info's to a fraction of a second
                    candidates = [piece for piece in pieces if piece[0] >= song["started_at"] - 1][:3]
                for _, url in candidates:
                    if url in checked:
                        continue
                    checked.add(url)
                    tags = read_id3(self.fetch(url, {"Range": f"bytes=0-{TAG_BYTES - 1}"}))
                    if not same_song(tags, song):
                        continue
                    found = SPOTIFY_ID.search(tags.get("COMM", b""))
                    if not found:
                        self.logger.log.debug(f"No Spotify ID for {station}: {song['artist']} - {song['song']}")
                        return
                    with self.history_lock:
                        song["spotify"] = found.group().decode()
                        self.save_history()
                    self.logger.log.debug(f"Spotify ID {song['spotify']} for {station}: {song['artist']} - {song['song']}")
                    return
                if checked and len(candidates) == 3:
                    # The song's first pieces are listed and none had its tags. It's not going to show up.
                    break
            except Exception as e:
                self.logger.log.debug(f"Could not read the tags in the HLS stream of {station}: {e}")
            time.sleep(SPOTIFY_POLL_SECONDS)
        self.logger.log.debug(f"Didn't find {station}: {song['artist']} - {song['song']} in the HLS stream")

    def hls_pieces(self, station):
        # The pieces listed in the station's HLS stream now, oldest first: [(start time, url)].
        # Any quality has the same tags, so the smallest.
        base = f"{self.audio_base_url}/hls/{station}"
        pieces, start = [], None
        for line in self.fetch(f"{base}/aac_lofi.m3u8").decode("utf-8", "replace").splitlines():
            line = line.strip()
            if line.startswith("#EXT-X-PROGRAM-DATE-TIME:"):
                start = parse_pdt(line.split(":", 1)[1])
            elif line and not line.startswith("#") and start is not None:
                pieces.append((start, f"{base}/{line}"))
                start = None
        return pieces

    def fetch(self, url, headers=None):
        response = self.tag_http.request("GET", url, headers=headers or {})
        if response.status not in (200, 206):
            raise RuntimeError(f"HTTP {response.status} from {url}")
        return response.data


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

    def check_break(self):
        # Song info is coming. After a listening break, Recently played starts afresh: before the
        # songs the server sends on connecting are added.
        now = time.time()
        if self.last_heard is not None and now - self.last_heard > LISTENING_BREAK_SECONDS:
            hours = (now - self.last_heard) / 3600
            self.logger.log.info(f"No song info for {hours:.1f} hours. Recently played starts afresh.")
            with self.history_lock:
                self.history.clear()
                self.save_history()
        self.last_heard = now

    def load_history(self):
        # The songs saved by the last run, unless that was before a listening break. The file is
        # saved on every new song on any station, so its time is about when the last run stopped.
        try:
            saved_at = os.path.getmtime(HISTORY_FILE)
            if time.time() - saved_at > LISTENING_BREAK_SECONDS:
                hours = (time.time() - saved_at) / 3600
                self.logger.log.info(f"Last listened {hours:.1f} hours ago. Recently played starts afresh.")
                return
            self.last_heard = saved_at
            with open(HISTORY_FILE, encoding="utf-8") as f:
                saved = json.load(f)
            for station, songs in saved.items():
                for song in songs:
                    entry = {
                        "artist": str(song["artist"]),
                        "song": str(song["song"]),
                        "started_at": float(song["started_at"]),
                    }
                    if SPOTIFY_ID.fullmatch(str(song.get("spotify", "")).encode()):
                        entry["spotify"] = song["spotify"]
                    self.history[station].append(entry)
                trim_history(self.history[station])
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
            self.logger.log.warning(f"Could not read the song history from {HISTORY_FILE}: {e}")

    def save_history(self):
        # Write a new file and swap it in, so the player stopping halfway can't leave it broken
        with self.history_lock:
            recent = {station: [dict(song) for song in songs] for station, songs in list(self.history.items())}
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
