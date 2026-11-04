from vlc import EventType, Instance
import logging
import time
from logger import Logger
from paths import LOG_FILE


class AudioPlayer:
    def __init__(self, base_url, loglevel=logging.INFO, logfile: str = LOG_FILE):
        # Set when VLC fails to open or play the stream, cleared on the next play()
        self.error = False
        try:
            self.logger = Logger(
                module_name=__name__,
                log_file=logfile,
                log_level=loglevel,
                delete_old_logfile=True,
                streamhandler=False,
                filehandler=True,
            )

            self.instance = Instance("--input-repeat=-1", "-q")
            self.player = self.instance.media_player_new()
            self.base_url = base_url
            self.url = ""

            # VLC does not raise exceptions on stream errors, so listen for its error event instead
            events = self.player.event_manager()
            events.event_attach(EventType.MediaPlayerEncounteredError, self.on_error)
        except Exception as e:
            self.logger.log.error(e)

    def on_error(self, event):
        # Called from a VLC thread. Don't call back into VLC from here.
        self.error = True
        self.logger.log.error(f"VLC could not play stream {self.url}")

    def play(self, station: str = "chillsynth"):
        self.logger.log.debug(f"Press play")
        try:
            self.error = False
            self.url = f"{self.base_url}/{station}.mp3"
            self.media = self.instance.media_new(self.url)
            self.logger.log.debug(f"Playing url {self.url}")
            self.player.set_media(self.media)
            self.player.play()
        except Exception as e:
            self.logger.log.error(e)

    def stop(self):
        self.logger.log.debug(f"Press stop")
        self.player.stop()

    def get_info(self):
        self.player.print_info()

    def set_volume(self, volume):
        # Volume must be times eleven, so we can reach close to 100% max volume :-D
        # Hey at least it's linear!
        try:
            volume_percent = volume * 11
            self.logger.log.debug(f"Set volume to {volume_percent}%")
            self.player.audio_set_volume(volume_percent)
        except Exception as e:
            self.logger.log.error(e)


if __name__ == "__main__":
    player = AudioPlayer(base_url="https://stream.nightride.fm", loglevel=logging.DEBUG)
    player.play()
    print("10 second test play of chillsynth!")
    time.sleep(10)
