import curses
from curses import wrapper
from curses.textpad import rectangle
import logging
import time
import threading
import random
import configparser

from NightrideAPI import NightRideAPI

class RadioInterface:
    def __init__(self, loglevel: str='error', logfile: str='radio.log'):
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
        
        fileHandler = logging.FileHandler(logfile)
        fileHandler.setFormatter(formatter)
        fileHandler.setLevel(loglevel)
        self.logger.addHandler(fileHandler)
        self.logger.info(f'Logging to {logfile}')
            
        self.logger.debug(f'Logger setup finished for {__name__} module')
        ### Logger setup finished ###
        
        ### Read config ###
        self.config = configparser.ConfigParser()
        self.config.read('Nightride.ini')
        
        self.LCD1602_MODULE = self.config.getboolean('ADDONS', 'LCD1602')
        if self.LCD1602_MODULE:
            self.logger.debug(f'Initializing lcd module')
            import RGB1602
            self.lcd = RGB1602.RGB1602(16,2, 'error', alertlog='radio.log')
        
        self.api = NightRideAPI(loglevel='debug', logfile='radio.log')
        
        stationlist = self.config.items('STATIONS')
        self.stations = []
        for key, value in stationlist:
            self.stations.append(value)
            
        self.VU_METER = self.config.getboolean('SETTINGS', 'VU_METER')
        self.volume = 4
        self.api.audioPlayer.set_volume(self.volume)
        self.station = self.config['SETTINGS']['default_station']
        self.orig_time = False
        self.now_playing = {"artist": "", "song": ""}
        
        wrapper(self.main)
        
        
            
    def run(self):
        self.api.start()
        # wrapper(self.main)
        
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
        curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_WHITE)
        
        
        stdscr.addstr(2, 5, "NIGHTRIDE", curses.color_pair(2))
        stdscr.addstr(2, 15, "FM", curses.color_pair(2))
        stdscr.addstr(4, 3, "...............................................")
        
        stdscr.refresh()
        self.menu_win = curses.newwin(0, 0, 1, 30)
        self.station_win = curses.newwin(1, 30, 3, 5)
        self.vol_win = curses.newwin(1, 18, 3, 31)
        self.now_playing_win = curses.newwin(2, 40, 6, 5)
        
        self.set_station(self.station)
        self.set_volume_slider(self.volume)
        self.t1 = time.perf_counter()
        while True:
            self.read_key(stdscr)
            self.set_played()
            self.set_now_playing()
            self.draw_vu_meter()
            self.draw_menu_bar(stdscr)
            stdscr.refresh()
            self.station_win.refresh()
            self.vol_win.refresh()
            self.now_playing_win.refresh()
            time.sleep(.1)
    
    def read_key(self, stdscr):
        key = ''
        try:
            key = stdscr.getkey()
            self.logger.debug(f'User pressed key {key}')
        except curses.error as e:
            # No input from user. Let's pass.
            pass
        
        if key == "+":
            if self.volume < 9:
                self.volume += 1
                self.set_volume_slider(self.volume)
                self.api.audioPlayer.set_volume(self.volume)
            
        if key == "-":
            if self.volume > 0:
                self.volume -= 1
                self.set_volume_slider(self.volume)
                self.api.audioPlayer.set_volume(self.volume)
        
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
            # Yeah there is something wrong here... needs fixing.
            # Some windows vanish
            self.station_win.refresh()
            self.now_playing_win.refresh()
            
            self.station_win = curses.newwin(1, 23, 3, 5)
            n = self.stations.index(self.station)
            self.station_win.addstr(f'station {n+1}: {self.station}')
            self.station_win.refresh()
            
            self.set_volume_slider(self.volume)
            stdscr.refresh()
            
        if key == "s":
            self.VU_METER = not self.VU_METER
            self.config.set('SETTINGS', 'VU_METER', f'{self.VU_METER}')
            self.save_config()
        
        if key == "KEY_F(12)":
            exit()
        
    
    def save_config(self):
        with open('Nightride.ini', 'w') as configfile:
            self.config.write(configfile)
            
    def set_volume_slider(self, volume):
        self.logger.debug(f'Set volume slider to {volume}')
        try:
            
            # slider = list('VOL: -==========+')
            slider = list('VOL: ◄----------►')
            slider[int(volume) + 6] = str(volume)
            
            self.vol_win = curses.newwin(1, 18, 3, 31)
            self.vol_win.addstr("".join(slider))
            self.vol_win.refresh()
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
    
    def set_now_playing(self):
        try:
            if self.now_playing == self.api.now_playing[self.station]:
                # Already playing the song, do nothing.
                pass
            else:
                self.now_playing = self.api.now_playing[self.station]
                artist = self.now_playing['artist']
                song = self.now_playing['song']
                self.logger.debug(f'Set now playing => A:{artist} S:{song}')
                
                artist = self.check_if_too_long(artist)
                song = self.check_if_too_long(song)
                
                # if not skip_timer_reset:
                # self.t1 = time.perf_counter()
                
                self.now_playing_win = curses.newwin(2, 40, 6, 5)
                self.now_playing_win.addstr(0, 0, f'Artist: ')
                self.now_playing_win.addstr(0, 8, f' {artist} ', curses.color_pair(3))
                self.now_playing_win.addstr(1, 2, f'Song: ')
                self.now_playing_win.addstr(1, 8, f' {song} ', curses.color_pair(4))
                self.now_playing_win.refresh()
                
                if self.LCD1602_MODULE:
                    self.lcd.printOnTwoRows(argTopRow=artist,argBotRow=song, color='GREEN', turnOffAfter=False)
        except KeyError as e:
            self.logger.warning(f'No data for station {self.station} yet')
        except Exception as e:
            self.logger.error(f'Failed to set now playing: {e}')
    
    def set_played(self):
        try:
            current_song_start = self.api.now_playing[self.station]['started_at']
        except KeyError:
            self.logger.warning("Could not get current_song_start")
            current_song_start = 0
        timenow = time.perf_counter()
        timedelta = int(timenow) - int(current_song_start)
        minutes = int(timedelta / 60)
        seconds = timedelta % 60
        
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
        self.api.audioPlayer.play(station)
        try:
            self.station = station
            self.station_win = curses.newwin(1, 23, 3, 5)
            self.station_win.addstr(f'station {n+1}: {self.station}')
            self.station_win.refresh()
        except:
            self.logger.error(f'Failed to set station to {station}')
    
    def draw_vu_meter(self):
        # Obviously, this VU meter is purely cosmetic :-)
        
        if self.VU_METER:
            icons = list("▁▂▃▄▅▆▇█")
            meter_list = []
            for i in range(10):
                meter_list.append(random.choice(icons))
            meter = "".join(meter_list)
        else:
            meter = ""
        
        try:
            vu_win = curses.newwin(1, 15, 8, 35)
            vu_win.addstr(0, 0, meter)
            vu_win.refresh()
        except:
            self.logger.error(f'Failed to draw VU meter')
    
    def draw_menu_bar(self, stdscr):
        max_rows, max_cols = stdscr.getmaxyx()
        self.menu_win = curses.newwin(1, max_cols, 0, 0)
        # self.bot_menu_win = curses.newwin(1, max_cols, 12, 0)
        try:
            self.menu_win.addstr("F1: HELP | F2: STATION | F12: QUIT".ljust(max_cols), curses.color_pair(5))
        except curses.error:
            # Accursed curses raises an error if you write in the last column.
            # We will discard that...
            pass
        # try:
        #     pattern = list("░▒▓█▓▒░"*20)
        #     self.bot_menu_win.addstr("".join(pattern[0:max_cols]), curses.color_pair(2))
        #     # self.bot_menu_win.addstr("asdf", curses.color_pair(3))
        # except curses.error:
        #     pass
        self.menu_win.refresh()
        # self.bot_menu_win.refresh()
if __name__ == '__main__':
    
    radio = RadioInterface(loglevel='debug')
    
    if radio.LCD1602_MODULE:
            radio.lcd.clear()
            radio.lcd.turnOff()