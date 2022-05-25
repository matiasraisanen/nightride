import argparse
import configparser
import curses
import curses.panel
import curses.textpad
import logging
import os
import random
import time

from NightrideAPI import NightRideAPI

class RadioInterface:
    def __init__(self, loglevel: str='error', logfile: str='radio.log'):
        ### ArgParse ###
        # parser = argparse.ArgumentParser(description='Text-based user interface for Nightride.fm.')

        # args = parser.parse_args()
        # parser.print_usage()

        ### Logger setup ###
        
        # Delete old logfile if it exists
        if os.path.exists(logfile):
            os.remove(logfile)
        else:
            pass

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
        
        ### Read config ###
        self.config = configparser.ConfigParser()
        self.config.read('settings.ini')
        
        self.LCD1602_MODULE = self.config.getboolean('ADDONS', 'LCD1602')
        if self.LCD1602_MODULE:
            self.logger.debug(f'Initializing lcd module')
            import RGB1602
            self.lcd = RGB1602.RGB1602(16,2, 'error', logfile='radio.log')
        
        self.api = NightRideAPI(loglevel=loglevel, logfile='radio.log')
        
        stationlist = self.config.items('STATIONS')
        self.stations = []
        for key, value in stationlist:
            self.stations.append(value)
            
        self.VU_METER = self.config.getboolean('SETTINGS', 'VU_METER')
        self.volume = 4
        self.api.audioPlayer.set_volume(self.volume)
        self.station = self.config['SETTINGS']['default_station']
        self.orig_time = False
        self.now_playing = {
            "artist": "", 
            "artist_short": "", 
            "song": "", 
            "song_short": ""}
        self.version = "v1.0"
        try:
            curses.wrapper(self.main)
        except Exception as e:
            print("An error caused the program to crash. See radio.log for details")
            self.logger.error(e)
        
        
    def main(self, stdscr):
        # curses.noecho()
        curses.curs_set(0)
        curses.start_color()
        
        stdscr.nodelay(True)
        
        curses.init_pair(1, curses.COLOR_MAGENTA, curses.COLOR_BLACK)
        curses.init_pair(2, curses.COLOR_CYAN, curses.COLOR_BLACK)
        
        curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_CYAN)
        curses.init_pair(4, curses.COLOR_CYAN, curses.COLOR_MAGENTA)
        curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_WHITE)
        curses.init_pair(6, curses.COLOR_BLACK, curses.COLOR_MAGENTA)
        curses.init_pair(7, curses.COLOR_BLACK, curses.COLOR_RED)
        curses.init_pair(8, curses.COLOR_BLACK, curses.COLOR_GREEN)
        curses.init_pair(9, curses.COLOR_BLACK, curses.COLOR_BLUE)
        curses.init_pair(10, curses.COLOR_BLACK, curses.COLOR_BLACK)
        
        rows, cols = stdscr.getmaxyx()
        self.logger.debug(f'Window size at x:{cols} y:{rows}')
        if rows<11 or cols<52:
            self.logger.error(f'Window size too small to draw interface! Needs at least 52x11')
        
        self.draw_radio_frame(stdscr)
        self.draw_now_playing_win()
        
        self.set_station(self.station)
        self.set_volume_slider(self.volume)
        self.t1 = time.perf_counter()
        while True:
            self.read_key(stdscr)
            self.set_playtime()
            self.draw_now_playing_win()
            self.draw_vu_meter()
            self.draw_menu_bar(stdscr)
            self.draw_station_win()
            self.draw_volume_win()
            stdscr.refresh()
            time.sleep(.1)
    def draw_radio_frame(self,stdscr):
        # Draw a rectangle with single line
        # curses.textpad.rectangle(stdscr, 2, 2, 10, 50)
        
        # Draw a double line thick rectangle
        stdscr.addstr(2, 2, "╔═ --------- -- ════════════════════════════════╗")
        for i in range(7):
            stdscr.addstr(i+3, 2, f'║{str().center(47)}║')
        stdscr.addstr(10, 2, "╚═══════════════════════════════════════════════╝")
        
        # Draw the rest of the interface
        stdscr.addstr(2, 5, "NIGHTRIDE", curses.color_pair(2))
        stdscr.addstr(2, 15, "FM", curses.color_pair(2))
        stdscr.addstr(4, 3, "...............................................")
        
    def read_key(self, stdscr):
        key = ''
        try:
            key = stdscr.getkey()
            if key == "KEY_RESIZE":
                rows, cols = stdscr.getmaxyx()
                self.logger.debug(f'User resized the window to x:{cols} y:{rows}')
                self.draw_radio_frame(stdscr)
            else:
                self.logger.debug(f'User pressed key {key}')
        except curses.error as e:
            # No input from user. Let's pass.
            pass
        
        # Change channels inputting numbers
        if key in ["1", "2", "3", "4", "5", "6", "7", "8", "9"]:
            self.api.audioPlayer.stop()
            self.set_station(self.stations[int(key)-1])
        
        # Volume up
        if key == "+":
            if self.volume < 9:
                self.volume += 1
                self.set_volume_slider(self.volume)
                self.api.audioPlayer.set_volume(self.volume)
            
        # Volume down
        if key == "-":
            if self.volume > 0:
                self.volume -= 1
                self.set_volume_slider(self.volume)
                self.api.audioPlayer.set_volume(self.volume)
        
        # Legacy: change station with arrow keys
        # # Previous station
        # if key == "KEY_LEFT":
        #     self.logger.debug("Previous station")
        #     index_of_prev = self.stations.index(self.station) - 1
        #     if index_of_prev >= 0:
        #         prev_station = self.stations[index_of_prev]
        #         self.set_station(prev_station)
            
        # # Next station
        # if key == "KEY_RIGHT":
        #     self.logger.debug("Next station")
        #     index_of_next = self.stations.index(self.station) + 1
        #     if index_of_next < len(self.stations):
        #         next_station = self.stations[index_of_next]
        #         self.set_station(next_station)
            
        # Resize window
        if key == "KEY_RESIZE":
            self.station_win.refresh()
            self.now_playing_win.refresh()
            
            self.station_win = curses.newwin(1, 23, 3, 5)
            n = self.stations.index(self.station)
            self.station_win.addstr(f'station {n+1}: {self.station}')
            self.station_win.refresh()
            stdscr.refresh()
            
        # Disable VU meter
        if key == "v":
            self.VU_METER = not self.VU_METER
            self.config.set('SETTINGS', 'VU_METER', f'{self.VU_METER}')
            self.save_config()
        
        if key == "r":
            self.LCD1602_MODULE = not self.LCD1602_MODULE
            self.config.set('ADDONS', 'lcd1602', f'{self.VU_METER}')
            self.save_config()
            if not self.LCD1602_MODULE:
                self.lcd.clear()
                self.lcd.turnOff()
            else: 
                self.lcd.printOnTwoRows(argTopRow=self.now_playing['artist'],argBotRow=self.now_playing['song'], color='GREEN', turnOffAfter=False, freezeFor=0)
                self.lcd.setRGB((255,0,255))
        # Quit
        if key == "KEY_F(12)":
            if self.LCD1602_MODULE:
                self.lcd.clear()
                self.lcd.turnOff()
            exit()
        
        # Show "About" info
        if key == "KEY_F(1)":
            self.draw_popup_about(stdscr)
        # Show "Stations" panel
        if key == "KEY_F(2)":
            self.draw_popup_select_station(stdscr)
            
    def draw_popup_about(self, stdscr):
        self.panwin = curses.newwin(9,49, 2,2)
        self.panwin.erase()
        self.panwin.box()
        
        max_rows, max_cols = stdscr.getmaxyx()
        menu_win = curses.newwin(1, 11, 0, 0)
        menu_win_2 = curses.newwin(1, max_cols - 11, 0, 10)
        try:
            menu_win.addstr("F1: ABOUT ", curses.color_pair(3))
            menu_win_2.addstr("| F2: STATION | -/+: VOLUME | F12: QUIT".ljust(max_cols), curses.color_pair(5))
        except curses.error:
        # Accursed curses raises an error if you write in the last column.
        # We will discard that...
            pass
        menu_win.refresh()
        menu_win_2.refresh()
        
        self.panwin.addstr(0, 20, ">>ABOUT<<", curses.color_pair(5))
        self.panwin.addstr(2, 3, "AUTHOR:", curses.color_pair(3))
        self.panwin.addstr(2, 10, " Matias Räisänen 2022 ", curses.color_pair(6))
        
        self.panwin.addstr(3, 2, "CONTACT:", curses.color_pair(3))
        self.panwin.addstr(3, 10, " matias@matiasraisanen.com ", curses.color_pair(6))
        
        self.panwin.addstr(4, 3, "SOURCE:", curses.color_pair(3))
        self.panwin.addstr(4, 10, " github.com/matiasraisanen/nightride ", curses.color_pair(6))
        
        self.panwin.addstr(5, 2, "VERSION:", curses.color_pair(3))
        self.panwin.addstr(5, 10, f' {self.version}',  curses.color_pair(6))

        self.panwin.addstr(6, 2, "Player for Nightride.fm")
        self.panwin.addstr(7, 2, "(https://nightride.fm)")
        self.panwin.addstr(8, 3, "ENTER: [OK]", curses.color_pair(8))
        self.panwin.addstr(8, 31, "F1: [CLOSE]", curses.color_pair(7))

        panel = curses.panel.new_panel(self.panwin)
        panel.top()
        # NOTE: Update panels will crash on WIN10. Should figure out a workaround later!
        curses.panel.update_panels()
        stdscr.refresh()
        while True:
                key = ''
                try:
                    key = stdscr.getkey()
                    self.logger.debug(f'User pressed key {key}')
                except curses.error as e:
                    # No input from user. Let's pass.
                    pass
                
                if key == "KEY_F(1)" or key == "\n":
                    self.draw_radio_frame(stdscr)
                    break
                if key == "KEY_F(12)":
                    exit()
        
    def draw_popup_select_station(self, stdscr):
        
        # Draw menu with "station" active
        max_rows, max_cols = stdscr.getmaxyx()
        menu_win = curses.newwin(1, 12, 0, 0)
        menu_win_2 = curses.newwin(1, 14, 0, 11)
        menu_win_3 = curses.newwin(1, max_cols - 25, 0, 24)
        try:
            menu_win.addstr("F1: ABOUT |", curses.color_pair(5))
            menu_win_2.addstr(" F2: STATION ", curses.color_pair(3))
            menu_win_3.addstr("| ↑/↓: MOVE | F12: QUIT".ljust(max_cols), curses.color_pair(5))
        except curses.error:
        # Accursed curses raises an error if you write in the last column.
        # We will discard that...
            pass
        menu_win.refresh()
        menu_win_2.refresh()
        menu_win_3.refresh()
        
        self.panwin = curses.newwin(9,49, 2,2)
        self.panwin.erase()
        self.panwin.box()
        
        selected = self.stations.index(self.station)
        index_of_prev = self.stations.index(self.station) - 1
        if index_of_prev >= 0:
            prev_station = self.stations[index_of_prev]
        else:
            prev_station = ''
        
        index_of_next = self.stations.index(self.station) + 1
        if index_of_next < len(self.stations):
            next_station = self.stations[index_of_next]
        else: next_station = ''
    
        top = prev_station
        mid = self.stations[selected]
        bot = next_station
        
        self.panwin.addstr(0, 15, f'>>SELECT STATION<<', curses.color_pair(5))
        # self.panwin.addstr(2, 6, f'↑', curses.color_pair(5))
        self.panwin.addstr(3, 3, f'Station {selected+1}:')
        # self.panwin.addstr(4, 6, f'↓', curses.color_pair(5))
        
        # Draw top row
        if top == '':
            # Draw black on top row, if the selected station is first in list
            top_color = curses.color_pair(10)
        else: 
            top_color = curses.color_pair(9)
        self.panwin.addstr(2, 18, f'  {top.center(11)}  ', top_color)
        
        # Draw mid row
        self.panwin.addstr(3, 19, f'→ {mid.center(11)} ←', curses.color_pair(3))
        
        # Draw bot row
        if bot == '':
            # Draw black on bot row, if the selected station is last in list
            bot_color = curses.color_pair(10)
        else:
            bot_color = curses.color_pair(9)
        self.panwin.addstr(4, 18, f'  {bot.center(11)}  ', bot_color)
        
        # Draw "NOW PLAYING"-section
        self.panwin.addstr(5, 1, "...............................................")
        self.panwin.addstr(5, 3, "NOW.PLAYING")
        
        artist = self.api.now_playing[self.stations[selected]]['artist']
        artist = self.shorten(artist,37)
        song = self.api.now_playing[self.stations[selected]]['song']
        song = self.shorten(song,37)
        self.panwin.addstr(6, 2, f'Artist: ')
        self.panwin.addstr(6, 10, f'{artist}', curses.color_pair(3))
        self.panwin.addstr(7, 4, f'Song: ')
        self.panwin.addstr(7, 10, f'{song}', curses.color_pair(4))
        
        
        
        self.panwin.addstr(8, 3, "ENTER: [OK]", curses.color_pair(8))
        self.panwin.addstr(8, 31, "F2: [CLOSE]", curses.color_pair(7))

        panel = curses.panel.new_panel(self.panwin)
        panel.top()
        # NOTE: Update panels will crash on WIN10. Should figure out a workaround later!
        curses.panel.update_panels()
        stdscr.refresh()
        if self.LCD1602_MODULE:
            self.lcd.printOnTwoRows(argTopRow='Select station:',argBotRow=f'{mid}'.center(16), color='GREEN', turnOffAfter=False, freezeFor=0)
            self.lcd.setRGB((255,0,255))
        
        # User changing stations
        while True:
                key = ''
                try:
                    key = stdscr.getkey()
                   
                    if key == "KEY_UP":
                        # Check if top of list.
                        index_of_prev = selected - 1
                        if index_of_prev >= 0:
                            if index_of_prev == 0:
                                top = ''
                            else:
                                top = self.stations[selected-2]
                            mid = self.stations[selected-1]
                            bot = self.stations[selected]
                            selected -= 1
                            if selected > 0:
                                top = self.stations[selected-1]
                        else:
                            top = ''
                            
                    if key == "KEY_DOWN":
                        max_num = (len(self.stations) -1)
                        index_of_next = selected + 1
                        if index_of_next <= max_num:
                            mid = self.stations[selected+1]
                            top = self.stations[selected]
                            if index_of_next == max_num :
                                bot = ''
                            
                            selected += 1
                            if selected < max_num:
                                bot = self.stations[selected+1]
                        else:
                            bot = ''
                    if key == "KEY_F(2)":
                        self.draw_radio_frame(stdscr)
                        self.set_now_playing(redraw = True)
                        break
                    if key == "KEY_F(12)":
                        exit()
                    
                    mid = self.stations[selected]
                    
                    # Start drawing the channel selector
                    
                    # Draw top row
                    if top == '':
                        # Draw black on top row, if the selected station is first in list
                        top_color = curses.color_pair(10)
                    else: 
                        top_color = curses.color_pair(9)
                    self.panwin.addstr(2, 18, f'  {top.center(11)}  ', top_color)
                    
                    # Draw mid row
                    self.panwin.addstr(3, 3, f'Station {selected+1}:')
                    self.panwin.addstr(3, 19, f'→ {mid.center(11)} ←', curses.color_pair(3))
                    
                    # Draw bot row
                    if bot == '':
                        # Draw black on bot row, if the selected station is last in list
                        bot_color = curses.color_pair(10)
                    else:
                        bot_color = curses.color_pair(9)
                    self.panwin.addstr(4, 18, f'  {bot.center(11)}  ', bot_color)
                    
                    
                    # Set data for the "NOW PLAYING"-section
                    artist = self.api.now_playing[self.stations[selected]]['artist']
                    artist = self.shorten(artist,37)
                    song = self.api.now_playing[self.stations[selected]]['song']
                    song = self.shorten(song,37)
                    
                    # Draw the "NOW PLAYING"-section
                    self.panwin.addstr(6, 2, f'Artist: {artist.ljust(38)}')
                    self.panwin.addstr(6, 10, f'{artist}', curses.color_pair(3))
                    self.panwin.addstr(7, 4, f'Song: {song.ljust(38)}')
                    self.panwin.addstr(7, 10, f'{song}', curses.color_pair(4))
        
                    panel = curses.panel.new_panel(self.panwin)
                    panel.top()
                    # NOTE: Update panels will crash on WIN10. Should figure out a workaround later!
                    curses.panel.update_panels()
                    stdscr.refresh()
                
                    # User pressing "ENTER" will activate the selection
                    if key == curses.KEY_ENTER or key == 10 or key == 13 or key == "\n":
                        self.logger.debug(f'User selected station {self.stations[selected]} via F2')
                        self.set_station(self.stations[selected])
                        break
                    
                    if self.LCD1602_MODULE:
                        self.lcd.printOnTwoRows(argTopRow='Select station:',argBotRow=f'{mid}'.center(16), color='GREEN', turnOffAfter=False, freezeFor=0)
                        self.lcd.setRGB((255,0,255))
                except curses.error as e:
                        # No input from user. Let's pass.
                        pass
                    
    def save_config(self):
        with open('settings.ini', 'w') as configfile:
            self.config.write(configfile)
            
    def set_volume_slider(self, volume):
        self.logger.debug(f'Set volume slider to {volume}')
        try:
            slider = list('VOL: ◄----------►')
            slider[int(volume) + 6] = str(volume)
            
            self.vol_win = curses.newwin(1, 18, 3, 31)
            self.vol_win.addstr("".join(slider))
            self.vol_win.refresh()
        except:
            self.logger.error(f'Failed to set volume slider to {volume}')

    def shorten(self, word, max_length=29):
        if len(word) > max_length:
            self.logger.debug(f'Truncating {word} for interface')
            trunc_word = list(word[0:max_length])
            trunc_word[-3:] = "..."
            word = "".join(trunc_word)
            self.logger.debug(f'Truncated into {word}')
        return word
    
    def draw_now_playing_win(self):
        self.set_now_playing()
        artist = self.now_playing['artist_short']
        song = self.now_playing['song_short']

        self.now_playing_win = curses.newwin(2, 40, 6, 5)
        self.now_playing_win.addstr(0, 0, f'Artist: ')
        self.now_playing_win.addstr(1, 2, f'Song: ')
        
        # Erroneous artist/song titles will be replaced with ???ERR
        fail_title = '???ERR'
        try:
            self.now_playing_win.addstr(0, 8, f' {artist} ', curses.color_pair(3))
        except:
            self.now_playing_win.addstr(0, 8, f' {fail_title} ', curses.color_pair(3))
            
        try:
            self.now_playing_win.addstr(1, 8, f' {song} ', curses.color_pair(4))
        except:
            self.now_playing_win.addstr(1, 8, f' {fail_title} ', curses.color_pair(4))
            
        self.now_playing_win.refresh()

    def draw_station_win(self):
        n = self.stations.index(self.station)
        self.station_win = curses.newwin(1, 23, 3, 5)
        self.station_win.addstr(f'station {n+1}: {self.station}')
        self.station_win.refresh()

    def draw_volume_win(self):
        try:
            slider = list('VOL: ◄----------►')
            slider[int(self.volume) + 6] = str(self.volume)
            
            self.vol_win = curses.newwin(1, 18, 3, 31)
            self.vol_win.addstr("".join(slider))
            self.vol_win.refresh()
        except:
            self.logger.error(f'Failed to draw volume window')

    def set_now_playing(self, redraw = False):
        try:
            # Force LCD redraw with redraw = True
            if self.now_playing == self.api.now_playing[self.station] and redraw == False:
                # Already playing the song, do nothing.
                pass
            else:
                self.now_playing = self.api.now_playing[self.station]
                artist = self.now_playing['artist']
                song = self.now_playing['song']
                self.now_playing['artist_short'] = self.shorten(artist)
                self.now_playing['song_short'] = self.shorten(song)
                if self.LCD1602_MODULE:
                    self.lcd.printOnTwoRows(argTopRow=artist,argBotRow=song, color='GREEN', turnOffAfter=False, freezeFor=0)
                    # self.lcd.sequentialWrite(f'{artist}: {song}', pauseOnPunct=False, freezeFor=0, turnOffAfter=False)
                    self.lcd.setRGB((255,0,255))
        except KeyError as e:
            self.logger.warning(f'No data for station {self.station} yet')
        except Exception as e:
            self.logger.error(f'Failed to set now playing: {e}')
    
    def set_playtime(self):
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

        # if time_to_print != self.orig_time:
        try:
            time_played_win = curses.newwin(1, 20, 8, 5)
            time_played_win.addstr(time_to_print)
            time_played_win.refresh()
        except:
            self.logger.error(f'Failed to draw time played.')
        self.orig_time = time_to_print
        
        
    def set_station(self, station):
        self.logger.debug(f'Set station => {station}')
        try:
            self.station = station
            self.api.audioPlayer.play(station)
        except Exception as e:
            self.logger.error(f'Failed to set station to {station}')
            self.logger.error(e)
    
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
            self.menu_win.addstr("F1: ABOUT | F2: STATION | -/+: VOLUME | F12: QUIT".ljust(max_cols), curses.color_pair(5))
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
