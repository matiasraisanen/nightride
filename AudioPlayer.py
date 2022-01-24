
from vlc import Instance
import time

class AudioPlayer:
    def __init__(self):
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

if __name__ == '__main__':
    player = AudioPlayer()
    player.play()
    print("10 second test play of chillsynth!")
    time.sleep(10)