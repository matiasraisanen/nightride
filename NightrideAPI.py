
import configparser
import json
import logging
import re
import sseclient
import urllib3
import time
import threading

from AudioPlayer import AudioPlayer

class NightRideAPI:
    def __init__(self, loglevel: str='error', logfile: str='radio.log'):
        ### Read config ###
        config = configparser.ConfigParser()
        config.read('settings.ini')
        
        ### Logger setup ###
        if loglevel == 'info':
            loglevel = logging.INFO
        elif loglevel == 'debug':
            loglevel = logging.DEBUG
        elif loglevel == 'error':
            loglevel = logging.ERROR
        # else:
        #     raise Exception(f'Tried to use invalid loglevel \'{loglevel}\'')
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(loglevel)
        
        formatter = logging.Formatter(fmt='[%(asctime)s]-[%(name)s]-[%(levelname)s]: %(message)s', datefmt='%H:%M:%S')
        
        fileHandler = logging.FileHandler(logfile)
        fileHandler.setFormatter(formatter)
        fileHandler.setLevel(loglevel)
        self.logger.addHandler(fileHandler)
        self.logger.info(f'Logging to {logfile}')
            
        self.logger.debug(f'Logger setup finished for {__name__} module')
        ### Logger setup finished ###
        
        self.SSE_URL = config['URLS']['sse_url']
        AUDIO_STREAM_BASE_URL = config['URLS']['audio_stream_base_url']
        
        stationlist = config.items('STATIONS')
        self.stations = []
        for key, value in stationlist:
            self.stations.append(value)
        
        # Initialize SSE client
        self.init_client(self.SSE_URL)
        
        # Initialize audio player
        self.audioPlayer = AudioPlayer(base_url=AUDIO_STREAM_BASE_URL, loglevel=loglevel)
        
        
        for x in self.stations:
            self.logger.debug(f'Station {self.stations.index(x)}: {x}')
        
        self.station = 'chillsynth'
        self.now_playing = {}
        self.audioPlayer.play(self.station)

        thread_1 = threading.Thread(target=self.start)
        thread_1.daemon = True
        thread_1.start()

    def start(self):
        self.get_metadata()

    def fetch_sse(self, url, headers):
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        http = urllib3.PoolManager(cert_reqs='CERT_NONE', assert_hostname=False)
        try:
            return http.request('GET', url, preload_content=False, headers=headers)
        except Exception as e:
            self.logger.error("fetch_sse error")
            self.logger.error(e)

    def init_client(self, sse_url):
        self.logger.debug(f'Start SSE client')
        headers = {'Accept': 'text/event-stream'}
        try:
            self.response = self.fetch_sse(sse_url, headers)
            self.client = sseclient.SSEClient(self.response)
        except Exception as e:
            self.logger.error("init_client error")
            self.logger.error(e)

    def keep_sse_client_alive(self):
        self.logger.error("Keepalive event not received in time. Restarting sse client.")
        self.client.close()
        self.init_client(self.SSE_URL)

        metadata_handler_thread = threading.Thread(target=self.start)
        metadata_handler_thread.daemon = True
        metadata_handler_thread.start()

    def get_metadata(self):
        countdown_seconds = 90
        try:
            # Start a timer to keep SSE connection alive
            keep_alive_timer = threading.Timer(countdown_seconds, self.keep_sse_client_alive)  

            for event in self.client.events():
                self.logger.debug(f'SSE event received: {event.data}')
                if event.data != "keepalive":
                    data = json.loads(event.data)
                    station = data[0]['station']
                    start_time = time.perf_counter()
                    # start_time is used to estimate song lengths on the interface
                    if 'rekt' in data[0]['station']:
                        # Stations 'rekt' and 'rektory' have both the song title and the artist name in the 'title' section.
                        # These stations have to be handled in a different manner.
                        pattern = '(.+)\s-\s(.+)'
                        match = re.search(pattern, data[0]['title'])
                        if match:
                            artist = match.group(1)
                            title = match.group(2)
                        else:
                            artist = ""
                            title = data[0]['title']
                    else:
                        artist = data[0]['artist']
                        title = data[0]['title']
                        
                    current = {
                        "artist": artist,
                        "song": title,
                        "started_at": start_time
                    }
                    self.now_playing[station] = current
                    self.logger.debug(f'New song detected on {station} => {artist} - {title}')

                elif event.data == "keepalive":
                    # Keepalive events should be received every {countdown_seconds}.
                    # We wait for {countdown_seconds} to pass, after which we assume the connection has been dropped, and we need to restart it.
                    self.logger.debug(f'Keepalive detected, resfreshing {countdown_seconds}sec keepalive timer')
                    keep_alive_timer.cancel()
                    keep_alive_timer = threading.Timer(countdown_seconds, self.keep_sse_client_alive)  
                    keep_alive_timer.start()
                    
        except Exception as e:
            self.logger.error("get_metadata error")
            self.logger.error(e)

if __name__ == '__main__':
    nightRide = NightRideAPI(loglevel='debug')
    try:
        nightRide.start()
    except KeyboardInterrupt:
        nightRide.audioPlayer.stop()