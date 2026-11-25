import logging
import os
import queue
import subprocess
import sys
import threading
import time
import audio_streams
from logger import Logger
from paths import LOG_FILE, VLC_DIR

if VLC_DIR:
    # Use the VLC that comes with the Windows build. This must be set up before python-vlc is imported.
    os.environ["PYTHON_VLC_LIB_PATH"] = os.path.join(VLC_DIR, "libvlc.dll")
    os.environ["PYTHON_VLC_MODULE_PATH"] = os.path.join(VLC_DIR, "plugins")
    os.environ["VLC_PLUGIN_PATH"] = os.path.join(VLC_DIR, "plugins")
    if sys.platform == "win32":
        # libvlc.dll needs libvlccore.dll from the same folder
        _vlc_dll_dir = os.add_dll_directory(VLC_DIR)

from vlc import EventType, Instance, MediaStats, State

# A VLC call taking longer than this means the audio system is stuck
STUCK_SECONDS = 3
# How long a station gets to show up in the sound server before we call the output missing
OUTPUT_GRACE_SECONDS = 5
# Seconds to wait before each reconnect attempt when a stream drops. The last one repeats.
RETRY_DELAYS = [2, 5, 10, 30]
# Failed reconnects before showing a stream error. Reconnecting still goes on.
ATTEMPTS_BEFORE_ERROR = 3
# The stream server sends some seconds of past audio when a player connects, so the player stays
# that far behind the live stream. VLC's bitrate settles after a few seconds of playing, and if
# there is still no measurement this long after starting, something is wrong.
LAG_SETTLE_SECONDS = 4
LAG_TIMEOUT_SECONDS = 20
# A measurement outside this is wrong
MAX_LAG_SECONDS = 60
# Standard MP3 bitrates, in kbit/s. VLC's measured rate is rounded to the nearest one.
MP3_BITRATES = [32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320]


class AudioPlayer:
    # Plays the radio streams with VLC.
    #
    # All VLC calls run on a worker thread. If the sound server hangs, VLC can block for half a minute
    # when stopping a stream, and that must not freeze the interface.
    #
    # If the stream drops (network trouble, server restart), the worker reconnects to it.

    def __init__(self, base_url, loglevel=logging.INFO, logfile: str = LOG_FILE, vlc_args=()):
        # Set when the stream has failed to come back after several attempts
        self.error = False
        # Set while waiting to reconnect a dropped stream
        self.reconnecting = False
        # The station that should be playing, or None when stopped
        self.station = None
        # Set by VLC's callbacks when the stream ends or fails
        self.dropped = False
        self.attempts = 0
        self.retry_at = None
        self.output_checked = 0
        # Set when the stream plays but its sound doesn't reach the sound server
        self.no_output = False
        # When the current VLC call started, or None when idle
        self.busy_since = None
        self.playing_since = None
        # Seconds the audio heard is behind the live stream, or None before the first measurement.
        # Kept from the last connection until the new one is measured, as they are much alike.
        self.lag = None
        # Why the lag can't be measured, or None
        self.lag_problem = None
        # Whether the current connection has been measured
        self.lag_measured = False
        # For Help > Stream info: VLC's figures for the current connection, or None before it
        # plays, and how many times the station has been reconnected
        self.stats = None
        self.reconnects = 0
        # The volume asked for last, or None before the first
        self.wanted_volume = None
        # Set once a stream has started playing
        self.started = threading.Event()
        self.commands = queue.Queue()
        self.stopped = threading.Event()
        try:
            self.logger = Logger(
                module_name=__name__,
                log_file=logfile,
                log_level=loglevel,
                streamhandler=False,
                filehandler=True,
            )

            # The sound server remembers a volume for each media role, and gives it to new streams.
            # VLC's default role is shared with every video player, so ours is music.
            self.instance = Instance("--input-repeat=-1", "-q", "--role=music", *vlc_args)
            self.player = self.instance.media_player_new()
            self.base_url = base_url
            self.url = ""

            # VLC does not raise exceptions on stream errors, so listen for its events instead.
            # A live stream that drops just "ends", without an error.
            events = self.player.event_manager()
            events.event_attach(EventType.MediaPlayerEncounteredError, self.on_dropped)
            events.event_attach(EventType.MediaPlayerEndReached, self.on_dropped)
            events.event_attach(EventType.MediaPlayerPlaying, self.on_playing)

            worker = threading.Thread(target=self.run)
            worker.daemon = True
            worker.start()
        except Exception as e:
            self.logger.log.error(e)

    # VLC calls these from its own threads. Don't call back into VLC from here.

    def on_dropped(self, event):
        self.dropped = True
        self.logger.log.warning(f"Stream {self.url} stopped playing")

    def on_playing(self, event):
        # Each station is a new stream, and the sound server may give it a remembered volume, which
        # VLC then takes as its own. Set ours again.
        if self.wanted_volume is not None:
            self.commands.put(("volume", self.wanted_volume))
        if self.attempts:
            self.logger.log.info(f"Stream {self.url} is back")
        self.attempts = 0
        self.reconnecting = False
        self.error = False
        self.started.set()

    ### Commands. These return immediately, the worker thread carries them out. ###

    def play(self, station: str = "chillsynth"):
        self.logger.log.debug(f"Press play")
        self.commands.put(("play", station))

    def stop(self):
        self.logger.log.debug(f"Press stop")
        self.commands.put(("stop", None))

    def set_volume(self, volume):
        self.wanted_volume = volume
        self.commands.put(("volume", volume))

    def shutdown(self, timeout=2.0):
        # Stop playback before exiting, but don't wait forever for a stuck VLC
        self.stopped.clear()
        self.stop()
        if not self.stopped.wait(timeout):
            self.logger.log.warning("VLC did not stop in time. Exiting anyway.")

    @property
    def stuck(self):
        return self.busy_since is not None and time.time() - self.busy_since > STUCK_SECONDS

    ### Worker thread ###

    def run(self):
        while True:
            try:
                commands = [self.commands.get(timeout=0.5)]
            except queue.Empty:
                self.check_reconnect()
                if time.time() - self.output_checked > 1:
                    self.output_checked = time.time()
                    self.check_output()
                self.check_lag()
                continue

            # Commands may have queued up while VLC was busy. Only the newest station change
            # (or stop) and the newest volume matter.
            while True:
                try:
                    commands.append(self.commands.get_nowait())
                except queue.Empty:
                    break
            latest = {}
            for command, arg in commands:
                latest["volume" if command == "volume" else "media"] = (command, arg)

            for command, arg in latest.values():
                self.busy_since = time.time()
                try:
                    if command == "play":
                        self._play(arg)
                    elif command == "stop":
                        self._stop()
                    else:
                        self._set_volume(arg)
                except Exception as e:
                    self.logger.log.error(e)
                finally:
                    elapsed = time.time() - self.busy_since
                    self.busy_since = None
                if elapsed > STUCK_SECONDS:
                    self.logger.log.warning(f"VLC took {elapsed:.0f} seconds to {command}")

    def _play(self, station):
        self.station = station
        self.attempts = 0
        self.reconnects = 0
        self.retry_at = None
        self.reconnecting = False
        self.error = False
        self._start(station)

    def _start(self, station):
        self.dropped = False
        self.no_output = False
        self.lag_measured = False
        self.stats = None
        self.url = f"{self.base_url}/{station}.mp3"
        self.media = self.instance.media_new(self.url)
        self.logger.log.debug(f"Playing url {self.url}")
        self.player.set_media(self.media)
        self.player.play()
        self.playing_since = time.time()

    def _stop(self):
        self.station = None
        self.reconnecting = False
        self.player.stop()
        self.playing_since = None
        self.no_output = False
        self.stopped.set()

    def _set_volume(self, volume):
        # volume is VLC's percentage, 0 to 99 here
        self.logger.log.debug(f"Set volume to {volume}%")
        self.player.audio_set_volume(volume)

    def check_reconnect(self):
        if not self.dropped or self.station is None:
            return
        if self.player.get_state() not in (State.Ended, State.Error):
            # A late event from a stream we already moved on from
            self.dropped = False
            return
        now = time.time()
        if self.retry_at is None:
            delay = RETRY_DELAYS[min(self.attempts, len(RETRY_DELAYS) - 1)]
            self.retry_at = now + delay
            self.reconnecting = True
            self.logger.log.warning(f"Reconnecting to {self.station} in {delay} seconds")
        elif now >= self.retry_at:
            self.retry_at = None
            self.attempts += 1
            self.reconnects += 1
            if self.attempts >= ATTEMPTS_BEFORE_ERROR and not self.error:
                self.error = True
                self.logger.log.error(f"Stream {self.url} keeps failing. Still trying.")
            self._start(self.station)

    def check_lag(self):
        # How far behind the live stream the audio is: the seconds of audio received, less the
        # seconds played. VLC doesn't know the stream's bitrate, but measures the rate it reads it at.
        if self.playing_since is None or self.reconnecting or self.error:
            return
        playing_for = time.time() - self.playing_since
        played = self.player.get_time() / 1000
        stats = MediaStats()
        self.media.get_stats(stats)
        # VLC gives bytes per microsecond
        kbits = stats.demux_bitrate * 1_000_000 * 8 / 1000
        if played > 0:
            self.stats = {
                "received": stats.read_bytes,
                # Settles after a few seconds
                "kbits": kbits if played >= LAG_SETTLE_SECONDS else None,
                # Audio that came too late to play, data that couldn't be read, and gaps in the stream
                "lost": stats.lost_abuffers,
                "corrupted": stats.demux_corrupted,
                "discontinuities": stats.demux_discontinuity,
            }
        if played >= LAG_SETTLE_SECONDS:
            nearest = min(MP3_BITRATES, key=lambda rate: abs(rate - kbits))
            if abs(nearest - kbits) <= nearest * 0.05:
                kbits = nearest
            if kbits > 0 and stats.read_bytes:
                lag = stats.read_bytes / (kbits * 1000 / 8) - played
                if 0 <= lag <= MAX_LAG_SECONDS:
                    if not self.lag_measured:
                        self.logger.log.info(f"The audio is {lag:.1f} seconds behind the live stream ({kbits:.0f} kbit/s)")
                    self.lag = lag
                    self.lag_measured = True
                    self.set_lag_problem(None)
                    return
                self.set_lag_problem(f"The audio would be {lag:.1f} seconds behind the live stream, which can't be right")
                return
        # Only when it plays: a stream that doesn't start is a different problem
        if not self.lag_measured and playing_for > LAG_TIMEOUT_SECONDS and self.player.get_state() == State.Playing:
            self.set_lag_problem(f"VLC doesn't tell how far behind the live stream the audio is (played {played:.1f} s)")

    def set_lag_problem(self, problem):
        if problem == self.lag_problem:
            return
        if problem:
            self.logger.log.warning(f"Song info can't be synced with the audio: {problem}")
            self.lag = None
        elif self.lag_problem:
            self.logger.log.info("Song info is synced with the audio again")
        self.lag_problem = problem

    def check_output(self):
        # VLC keeps saying "playing" even when it can't open the audio output, e.g. when PipeWire is stuck.
        # Check that our stream really exists in the sound server.
        if (
            self.playing_since is None
            or self.error
            or self.reconnecting
            or time.time() - self.playing_since < OUTPUT_GRACE_SECONDS
            or not audio_streams.available()
        ):
            return
        try:
            found = audio_streams.find_own_stream() is not None
        except (OSError, subprocess.SubprocessError, ValueError):
            # Can't tell
            return
        if found == self.no_output:
            self.no_output = not found
            if self.no_output:
                self.logger.log.error("No audio output. Is the sound server (PipeWire or PulseAudio) stuck?")
            else:
                self.logger.log.info("Audio output is back")


if __name__ == "__main__":
    player = AudioPlayer(base_url="https://stream.nightride.fm", loglevel=logging.DEBUG)
    player.play()
    print("10 second test play of chillsynth!")
    time.sleep(10)
