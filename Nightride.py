
import configparser
import json
import logging
import re
import sseclient
import threading

# pip3 install python-vlc sseclient-py

# Local
from AudioPlayer import AudioPlayer
from RadioInterface import RadioInterface

try:
    import RGB1602
except:
    print("No RGBMODULE")



class NightRideRadio:
    def __init__(self,  loglevel: str='error', alertlog: str=False):
        ### Read config ###
        config = configparser.ConfigParser()
        config.read('Nightride.ini')
        
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
        
        # streamHandler = logging.StreamHandler()
        formatter = logging.Formatter(fmt='[%(asctime)s]-[%(name)s]-[%(levelname)s]: %(message)s', datefmt='%H:%M:%S')
        # streamHandler.setFormatter(formatter)
        
        # self.logger.addHandler(streamHandler)
        
        # Setup warn logging to file
        if alertlog:
            fileHandler = logging.FileHandler(alertlog, mode='w')
            fileHandler.setFormatter(formatter)
            fileHandler.setLevel(loglevel)
            self.logger.addHandler(fileHandler)
            self.logger.warning(f'Logging warnings to {alertlog}')
            
        self.logger.debug(f'Logger setup finished for {__name__} module')
        ### Logger setup finished ###
        
        self.SSE_URL = config['URLS']['SSE_URL']
        self.AUDIO_STREAM_BASE_URL = config['URLS']['AUDIO_STREAM_BASE_URL']
        
        stationlist = config.items('STATIONS')
        self.stations = []
        for key, value in stationlist:
            self.stations.append(value)
        
        # Setup LCD module, if present
        self.LCD1602_MODULE = config.getboolean('ADDONS', 'LCD1602')
        if self.LCD1602_MODULE:
            self.lcd = RGB1602.RGB1602(16,2, 'error', alertlog='radio.log')
            
        self.init_client()
        self.audioPlayer = AudioPlayer()
        
        # Start curses radio interace
        self.interface = RadioInterface(loglevel='debug', alertlog='radio.log')
        
        for x in self.stations:
            self.logger.debug(f'Station {self.stations.index(x)}: {x}')
        # n = int(input("Which station you wanna play? "))
        # self.station = self.stations[n]
        self.station = 'chillsynth'
        self.audioPlayer.play(self.station)

    def start(self):
        self.get_metadata(self.station)
        
    def fetch_sse(self, url, headers):
        http = urllib3.PoolManager()
        return http.request('GET', url, preload_content=False, headers=headers)


    def init_client(self):
        headers = {'Accept': 'text/event-stream'}
        self.response = self.fetch_sse(self.SSE_URL, headers)
        self.client = sseclient.SSEClient(self.response)
    
    def change_station(self, station):
        self.station = station
        self.get_metadata(station)
        self.play(station)
        self.interface.set_station(station)

    def get_metadata(self, station):
        self.logger.debug(f'Playing station {station}')
        for event in self.client.events():
            if event.data != "keepalive":
                data = json.loads(event.data)
                if data[0]['station'] == station:
                    if 'rekt' in station:
                        # Stations 'rekt' and 'rektory' have the song and artist metadata 
                        # both in 'title' section.
                        # We must handle those stations differently.
                        pattern = '(.+)\s-\s(.+)'
                        match = re.search(pattern, data[0]['title'])
                        artist = match.group(1)
                        title = match.group(2)
                    else:
                        artist = data[0]['artist']
                        title = data[0]['title']
                    # album = data[0]['album']
                    # comment = data[0]['comment']
                    self.logger.debug(f'Now playing => {artist} - {title}')
                    self.interface.set_now_playing(artist, title)
                    if self.LCD1602_MODULE:
                        self.lcd.printOnTwoRows(argTopRow=artist,argBotRow=title,
                    color='GREEN',
                    turnOffAfter=False)

if __name__ == '__main__':
    nightRide = NightRideRadio(loglevel='debug', alertlog='radio.log')
    try:
        nightRide.start()
    except KeyboardInterrupt:
        nightRide.audioPlayer.stop()
        
        if nightRide.LCD1602_MODULE:
            nightRide.lcd.clear()
            nightRide.lcd.turnOff()
