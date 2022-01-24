import curses
from curses import wrapper
from curses.textpad import rectangle
import logging
import time
import threading
import random
import configparser

class RadioInterface:
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
        
        # streamHandler = logging.StreamHandler()
        formatter = logging.Formatter(fmt='[%(asctime)s]-[%(name)s]-[%(levelname)s]: %(message)s', datefmt='%H:%M:%S')
        # streamHandler.setFormatter(formatter)
        
        # self.logger.addHandler(streamHandler)
        
        # Setup warn logging to file
        if alertlog:
            # fileHandler = logging.FileHandler(alertlog, mode='w')
            fileHandler = logging.FileHandler(alertlog)
            fileHandler.setFormatter(formatter)
            # fileHandler.setLevel(logging.DEBUG)
            fileHandler.setLevel(logging.WARNING)
            self.logger.addHandler(fileHandler)
            self.logger.warning(f'Logging warnings to {alertlog}')
            
        self.logger.debug(f'Logger setup finished for {__name__} module')
        ### Logger setup finished ###
        
         ### Read config ###
        config = configparser.ConfigParser()
        config.read('Nightride.ini')
        
        stationlist = config.items('STATIONS')
        self.stations = []
        for key, value in stationlist:
            self.stations.append(value)
            
        self.volume = 5
        self.station = 'chillsynth'
        self.orig_time = False
        
        t1 = threading.Thread(target=self.run)
        # t1.daemon = True
        t1.start()
        
    def run(self):
        wrapper(self.main)
        
    def main(self, stdscr):
        # curses.noecho()
        curses.curs_set(0)
        curses.start_color()
        
        stdscr.nodelay(True)
        rectangle(stdscr, 2, 2, 10, 50)
        
        curses.init_pair(1, curses.COLOR_MAGENTA, curses.COLOR_BLACK)
        curses.init_pair(2, curses.COLOR_CYAN, curses.COLOR_BLACK)
        
        curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_CYAN)
        curses.init_pair(4, curses.COLOR_CYAN, curses.COLOR_MAGENTA)
        
        stdscr.addstr(2, 5, "NIGHTRIDE", curses.color_pair(2))
        stdscr.addstr(2, 15, "FM", curses.color_pair(2))
        stdscr.addstr(4, 3, "...............................................")
        
        stdscr.refresh()
        
        self.station_win = curses.newwin(1, 30, 3, 5)
        self.vol_win = curses.newwin(1, 18, 3, 31)
        self.now_playing_win = curses.newwin(2, 40, 6, 5)
        
        self.set_station(self.station)
        self.set_volume_slider(self.volume)
        self.t1 = time.perf_counter()
        while True:
            self.read_key(stdscr)
            self.set_played()
            self.draw_vu_meter()
            stdscr.refresh()
            self.station_win.refresh()
            self.vol_win.refresh()
            self.now_playing_win.refresh()
            time.sleep(.1)
    
    def read_key(self, stdscr):
        key = ''
        try:
            key = stdscr.getkey()
            self.logger.debug(key)
        except curses.error as e:
            # self.logger.debug('No input from user')
            pass
        
        if key == "+":
            self.logger.debug("AUDIO PLAYER: VOLUME UP")
            if self.volume < 9:
                self.volume += 1
                self.set_volume_slider(self.volume)
            
        if key == "-":
            self.logger.debug("AUDIO PLAYER: VOLUME DOWN")
            if self.volume > 0:
                self.volume -= 1
                self.set_volume_slider(self.volume)
        
        if key == "KEY_LEFT":
            self.logger.debug("Previous station")
            index_of_prev = self.stations.index(self.station) - 1
            if index_of_prev >= 0:
                prev_station = self.stations[index_of_prev]
                self.set_station(prev_station)
            
        if key == "KEY_RIGHT":
            self.logger.debug("Next station")
            index_of_next = self.stations.index(self.station) + 1
            if index_of_next < len(self.stations):
                next_station = self.stations[index_of_next]
                self.set_station(next_station)
            
        if key == "KEY_RESIZE":
            self.station_win.refresh()
            self.now_playing_win.refresh()
            self.set_station(self.station)
            self.set_volume_slider(self.volume)
            self.set_now_playing(self.now_playing['artist'], self.now_playing['song'])
            stdscr.refresh()
            
        if key == "a":
            # Debug for setting a song
            self.set_now_playing('John Wayne', 'The song I like')
            
        if key == "q":
            exit()
        
    
    def set_volume_slider(self, volume):
        self.logger.debug(f'Set volume slider to {volume}')
        try:
            vol_win = curses.newwin(1, 18, 3, 31)
            slider = list('VOL: -==========+')
            slider[int(volume) + 6] = str(volume)
            
            vol_win.addstr("".join(slider))
            vol_win.refresh()
        except:
            self.logger.error(f'Failed to set volume slider to {volume}')
        
    def check_if_too_long(self, word):
        max_length = 30
        if len(word) > max_length:
            self.logger.debug(f'Truncating {word} for interface')
            trunc_word = list(word[0:max_length])
            trunc_word[-3:] = "..."
            word = "".join(trunc_word)
        return word
    
    def set_now_playing(self, artist, song):
        skip_timer_reset = False
        
        # Skip played-timer's reset if we're already playing the same song
        if artist == self.now_playing['artist'] and song == self.now_playing['song']:
            skip_timer_reset = True
            
        self.now_playing = {"artist": artist, "song": song}
        self.logger.debug(f'Set now playing => A:{artist} S:{song}')
        
        artist = self.check_if_too_long(artist)
        song = self.check_if_too_long(song)
            
        try:
            if not skip_timer_reset:
            self.t1 = time.perf_counter()
            
            now_playing_win = curses.newwin(2, 40, 6, 5)
            now_playing_win.addstr(0, 0, f'Artist: ')
            now_playing_win.addstr(0, 8, f' {artist} ', curses.color_pair(3))
            now_playing_win.addstr(1, 2, f'Song: ')
            now_playing_win.addstr(1, 8, f' {song} ', curses.color_pair(4))
            now_playing_win.refresh()
        except:
            self.logger.error(f'Failed to set nowplaying to A:{artist} S:{song}')
    
    def set_played(self):
        timenow = time.perf_counter()
        timedelta = int(timenow) - int(self.t1)
        minutes = int(timedelta / 60) # \d\d
        seconds = timedelta % 60    # \d\d
        
        time_to_print = f'Played: {str(minutes).zfill(2)}:{str(seconds).zfill(2)}'

        if time_to_print != self.orig_time:
            try:
                time_played_win = curses.newwin(1, 20, 8, 5)
                time_played_win.addstr(time_to_print)
                time_played_win.refresh()
            except:
                self.logger.erro(f'Failed to draw time played.')
        self.orig_time = time_to_print
        
        
    def set_station(self, station):
        self.logger.debug(f'Set station => {station}')
        n = self.stations.index(station)
        try:
            self.station = station
            station_win = curses.newwin(1, 30, 3, 5)
            
            station_win.addstr(f'station {n}: {self.station}')
            station_win.refresh()
            # stdscr.addstr(3, 5, f'station: {self.station}')
            # stdscr.refresh()
        except:
            self.logger.error(f'Failed to set station to {station}')
    
    def draw_vu_meter(self):
        # Obviously, this VU meter is purely cosmetic :-)
        icons = list("▁▂▃▄▅▆▇█")
        meter_list = []
        for i in range(10):
            meter_list.append(random.choice(icons))
        meter = "".join(meter_list)
        
        try:
            vu_win = curses.newwin(1, 15, 8, 35)
            vu_win.addstr(0, 0, meter)
            vu_win.refresh()
        except:
            self.logger.error(f'Failed to draw VU meter')
    
if __name__ == '__main__':
    radio = RadioInterface(alertlog='radio.log')