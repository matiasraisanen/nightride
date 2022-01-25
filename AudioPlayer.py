
from vlc import Instance
import logging
import time

class AudioPlayer:
    def __init__(self, loglevel: str='error', alertlog: str=False):

        ### Logger setup ###
        if loglevel == 'info':
            loglevel = logging.INFO
        elif loglevel == 'debug':
            loglevel = logging.DEBUG
        elif loglevel == 'error':
            loglevel = logging.ERROR
        else:
            raise Exception(f'Tried to use invalid loglevel \'{loglevel}\'')
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(loglevel)
        
        formatter = logging.Formatter(fmt='[%(asctime)s]-[%(name)s]-[%(levelname)s]: %(message)s', datefmt='%H:%M:%S')
        
        if alertlog:
            fileHandler = logging.FileHandler(alertlog)
            fileHandler.setFormatter(formatter)
            fileHandler.setLevel(loglevel)
            self.logger.addHandler(fileHandler)
            self.logger.info(f'Logging to {alertlog}')
            
        self.logger.debug(f'Logger setup finished for {__name__} module')
        ### Logger setup finished ###

        self.instance = Instance('--input-repeat=-1', '-q')
        self.player=self.instance.media_player_new()

    def play(self, station: str='chillsynth'):
        self.media=self.instance.media_new(f'https://stream.nightride.fm/{station}.m4a')
        self.player.set_media(self.media)
        self.player.play()

    def stop(self):
        self.player.stop()
    
    def get_info(self):
        self.player.print_info()

    def set_volume(self, volume):
        self.logger.debug(f'Set volume to {volume}')
        # Volume must be times eleven, so we can reach close to 100% max volume :-D
        # Hey at least it's linear!
        volume_percent = volume * 11
        self.player.audio_set_volume(volume_percent)

if __name__ == '__main__':
    player = AudioPlayer()
    player.play()
    print("10 second test play of chillsynth!")
    time.sleep(10)