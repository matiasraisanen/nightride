import array
import logging
import math
import shutil
import subprocess
import sys
import threading
import time
import audio_streams
from logger import Logger
from paths import LOG_FILE

if sys.platform == "win32":
    try:
        import win_audio
    except ImportError:
        win_audio = None

RATE = 22050
CHUNK_FRAMES = RATE // 20  # 50 ms of audio per measurement
CHUNK_BYTES = CHUNK_FRAMES * 2 * 4  # stereo, 32-bit float
# On Windows, the session's peak meter is read this often, and the highest value is shown every 50 ms
WIN_POLL_SECONDS = 0.01
FLOOR_DB = -40.0  # Level shown as an empty meter
CEILING_DB = 0.0  # Level shown as a full meter
DECAY_DB_PER_SECOND = 24.0
PEAK_HOLD_SECONDS = 1.5


class LevelMeter:
    # Measures the radio's audio level for the VU meter.
    #
    # On Linux, VLC plays through PulseAudio (or PipeWire's PulseAudio layer). We find VLC's stream there
    # by our process id and record just that stream with parec. The recording is taken after the stream's
    # volume is applied, so we add the volume back to show the level of the music itself.
    #
    # On Windows, we find our audio session by process id and read its peak meter (see win_audio.py).
    # The meter gives the loudest samples rather than the average, so the bars run a bit higher there.

    def __init__(self, loglevel=logging.INFO, logfile: str = LOG_FILE):
        self.logger = Logger(
            module_name=__name__,
            log_file=logfile,
            log_level=loglevel,
            streamhandler=False,
            filehandler=True,
        )

        # Recording only runs while the meter is enabled
        self.enabled = False
        self.levels = [FLOOR_DB, FLOOR_DB]
        self.peaks = [FLOOR_DB, FLOOR_DB]
        self.peak_times = [0.0, 0.0]
        self.updated = 0.0

        if sys.platform == "win32":
            self.available = win_audio is not None
            # What the meter shows when it isn't available
            self.missing = "Needs pycaw"
            run = self.run_windows
        else:
            self.available = bool(shutil.which("parec") and audio_streams.available())
            self.missing = "Needs parec and pactl"
            run = self.run
        if not self.available:
            self.logger.log.warning(f"VU meter is not available: {self.missing}")
            return

        thread = threading.Thread(target=run)
        thread.daemon = True
        thread.start()

    def get(self):
        # Returns ([left, right] levels, [left, right] peaks) in dB.
        # If no audio has arrived lately (paused, buffering, muted), let the meter fall.
        idle = max(0.0, time.time() - self.updated - 0.1)
        decay = DECAY_DB_PER_SECOND * idle
        levels = [max(FLOOR_DB, level - decay) for level in self.levels]
        peaks = [max(FLOOR_DB, peak - decay) for peak in self.peaks]
        return levels, peaks

    def run(self):
        while True:
            stream = self.find_stream() if self.enabled else None
            if stream is None:
                time.sleep(0.5)
                continue
            try:
                self.record(*stream)
            except Exception as e:
                self.logger.log.error(f"VU meter recording failed: {e}")
                time.sleep(1)

    def find_stream(self):
        # Returns (sink input index, volume in dB) of our own audio stream, or None
        try:
            return audio_streams.find_own_stream()
        except (OSError, subprocess.SubprocessError, ValueError) as e:
            self.logger.log.debug(f"Could not list audio streams: {e}")
            return None

    def record(self, index, gain_db):
        self.logger.log.debug(f"Recording audio stream {index} for the VU meter")
        process = subprocess.Popen(
            [
                "parec",
                f"--monitor-stream={index}",
                "--format=float32le",
                f"--rate={RATE}",
                "--channels=2",
                "--latency-msec=50",
                "--raw",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        checked = time.time()
        try:
            while self.enabled:
                data = process.stdout.read(CHUNK_BYTES)
                if len(data) < CHUNK_BYTES:
                    # The stream went away, e.g. when changing stations
                    return
                samples = array.array("f", data)
                levels = [self.to_db(self.rms(channel)) for channel in (samples[0::2], samples[1::2])]
                self.update(levels, gain_db)

                # Follow volume changes, and notice if VLC has moved to a new stream
                if time.time() - checked > 1:
                    checked = time.time()
                    stream = self.find_stream()
                    if stream is None or stream[0] != index:
                        return
                    gain_db = stream[1]
        finally:
            process.kill()
            process.wait()

    ### Windows ###

    def run_windows(self):
        win_audio.init_thread()
        while True:
            session = self.find_session() if self.enabled else None
            if session is None:
                time.sleep(0.5)
                continue
            try:
                self.meter_session(session)
            except Exception as e:
                self.logger.log.error(f"VU meter failed: {e}")
                time.sleep(1)

    def find_session(self):
        try:
            return win_audio.find_own_session()
        except Exception as e:
            self.logger.log.debug(f"Could not list audio sessions: {e}")
            return None

    def meter_session(self, session):
        self.logger.log.debug(f"Reading the audio session's meter for the VU meter, {session.channels} channels")
        gain_db = session.gain_db()
        checked = time.time()
        while self.enabled:
            # The highest peak of each channel over one measurement
            peaks = [0.0, 0.0]
            end = time.time() + CHUNK_FRAMES / RATE
            while time.time() < end:
                peaks = [max(old, new) for old, new in zip(peaks, session.peaks())]
                time.sleep(WIN_POLL_SECONDS)
            self.update([self.to_db(value) for value in peaks], gain_db)

            # Follow volume changes, and notice if the sound has moved, e.g. to another output device
            if time.time() - checked > 1:
                checked = time.time()
                session = self.find_session()
                if session is None:
                    return
                gain_db = session.gain_db()

    ### Both ###

    def update(self, levels_db, gain_db):
        # levels_db: [left, right] levels as measured, after the volume (gain_db) was applied
        now = time.time()
        elapsed = min(0.2, now - self.updated)
        for i, measured in enumerate(levels_db):
            if math.isinf(gain_db):
                # Muted. There is nothing to measure.
                level = FLOOR_DB
            else:
                level = measured - gain_db

            # The bar follows the average level: jumps up fast, falls slowly
            self.levels[i] = max(level, self.levels[i] - DECAY_DB_PER_SECOND * elapsed)
            self.levels[i] = min(CEILING_DB, max(FLOOR_DB, self.levels[i]))

            # The peak marker remembers the highest point the bar reached. It holds for a moment, then falls.
            if self.levels[i] >= self.peaks[i]:
                self.peaks[i] = self.levels[i]
                self.peak_times[i] = now
            elif now - self.peak_times[i] > PEAK_HOLD_SECONDS:
                self.peaks[i] = max(self.levels[i], self.peaks[i] - DECAY_DB_PER_SECOND * elapsed)
        self.updated = now

    def rms(self, samples):
        # The average level
        return math.sqrt(sum(v * v for v in samples) / len(samples))

    def to_db(self, value):
        return 20 * math.log10(value) if value > 0 else -math.inf
