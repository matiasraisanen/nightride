from vlc import EventType, Instance, State
import logging
import queue
import subprocess
import threading
import time
import audio_streams
from logger import Logger
from paths import LOG_FILE

# A VLC call taking longer than this means the audio system is stuck
STUCK_SECONDS = 3
# How long a station gets to show up in the sound server before we call the output missing
OUTPUT_GRACE_SECONDS = 5
# Seconds to wait before each reconnect attempt when a stream drops. The last one repeats.
RETRY_DELAYS = [2, 5, 10, 30]
# Failed reconnects before showing a stream error. Reconnecting still goes on.
ATTEMPTS_BEFORE_ERROR = 3


class AudioPlayer:
    # Plays the radio streams with VLC.
    #
    # All VLC calls run on a worker thread. If the sound server hangs, VLC can block for half a minute
    # when stopping a stream, and that must not freeze the interface.
    #
    # If the stream drops (network trouble, server restart), the worker reconnects to it.

    def __init__(self, base_url, loglevel=logging.INFO, logfile: str = LOG_FILE):
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
        self.commands = queue.Queue()
        self.stopped = threading.Event()
        try:
            self.logger = Logger(
                module_name=__name__,
                log_file=logfile,
                log_level=loglevel,
                delete_old_logfile=False,
                streamhandler=False,
                filehandler=True,
            )

            self.instance = Instance("--input-repeat=-1", "-q")
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
        if self.attempts:
            self.logger.log.info(f"Stream {self.url} is back")
        self.attempts = 0
        self.reconnecting = False
        self.error = False

    ### Commands. These return immediately, the worker thread carries them out. ###

    def play(self, station: str = "chillsynth"):
        self.logger.log.debug(f"Press play")
        self.commands.put(("play", station))

    def stop(self):
        self.logger.log.debug(f"Press stop")
        self.commands.put(("stop", None))

    def set_volume(self, volume):
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
        self.retry_at = None
        self.reconnecting = False
        self.error = False
        self._start(station)

    def _start(self, station):
        self.dropped = False
        self.no_output = False
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
        # Volume must be times eleven, so we can reach close to 100% max volume :-D
        # Hey at least it's linear!
        volume_percent = volume * 11
        self.logger.log.debug(f"Set volume to {volume_percent}%")
        self.player.audio_set_volume(volume_percent)

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
            if self.attempts >= ATTEMPTS_BEFORE_ERROR and not self.error:
                self.error = True
                self.logger.log.error(f"Stream {self.url} keeps failing. Still trying.")
            self._start(self.station)

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
