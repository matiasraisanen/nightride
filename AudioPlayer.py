from vlc import Instance
import logging
import time
from logger import Logger


class AudioPlayer:
    def __init__(self, base_url, loglevel=logging.INFO, logfile: str = "radio.log"):
        try:
            self.logger = Logger(
                module_name=__name__,
                log_file=logfile,
                log_level=loglevel,
                delete_old_logfile=True,
                streamhandler=True,
                filehandler=True,
            )

            self.instance = Instance("--input-repeat=-1", "-q")
            self.player = self.instance.media_player_new()
            self.base_url = base_url
        except Exception as e:
            self.logger.log.error(e)

    def play(self, station: str = "chillsynth"):
        self.logger.log.debug(f"Press play")
        try:
            self.media = self.instance.media_new(f"{self.base_url}/{station}.m4a")
            self.logger.log.debug(f"Playing url {self.base_url}/{station}.m4a")
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
    player = AudioPlayer(loglevel=logging.DEBUG, logfile="radio.log")
    player.play()
    print("10 second test play of chillsynth!")
    time.sleep(10)
