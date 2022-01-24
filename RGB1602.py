# -*- coding: utf-8 -*-
from enum import Enum
import time
from smbus import SMBus
import logging

# from getch import _Getch

b = SMBus(1)

# Device I2C Arress
LCD_ADDRESS = (0x7c >> 1)   # 0111 1100
RGB_ADDRESS = (0xc0 >> 1)   # 1100 0000

# color define

REG_RED = 0x04      # 0000 0100
REG_GREEN = 0x03    # 0000 0011
REG_BLUE = 0x02     # 0000 0010
REG_MODE1 = 0x00    # 0000 0000
REG_MODE2 = 0x01    # 0000 0001
REG_OUTPUT = 0x08   # 0000 1000
LCD_CLEARDISPLAY = 0x01     # 0000 0001
LCD_RETURNHOME = 0x02       # 0000 0010
LCD_ENTRYMODESET = 0x04     # 0000 0100
LCD_DISPLAYCONTROL = 0x08   # 0000 1000
LCD_CURSORSHIFT = 0x10      # 0001 0000
LCD_FUNCTIONSET = 0x20      # 0010 0000
# Character Generator RAM(CGRAM) address
LCD_SETCGRAMADDR = 0x40     # 0100 0000
# Display Data RAM(DDRAM) address
LCD_SETDDRAMADDR = 0x80     # 1000 0000

# flags for display entry mode
LCD_ENTRYRIGHT = 0x00           # 0000 0000
LCD_ENTRYLEFT = 0x02            # 0000 0010
LCD_ENTRYSHIFTINCREMENT = 0x01  # 0000 0001
LCD_ENTRYSHIFTDECREMENT = 0x00  # 0000 0000

# flags for display on/off control
LCD_DISPLAYON = 0x04    # 0000 0100
LCD_DISPLAYOFF = 0x00   # 0000 0000
LCD_CURSORON = 0x02     # 0000 0010
LCD_CURSOROFF = 0x00    # 0000 0000
LCD_BLINKON = 0x01      # 0000 0001
LCD_BLINKOFF = 0x00     # 0000 0000

# flags for display/cursor shift
LCD_DISPLAYMOVE = 0x08  # 0000 1000
LCD_CURSORMOVE = 0x00   # 0000 0000
LCD_MOVERIGHT = 0x04    # 0000 0100
LCD_MOVELEFT = 0x00     # 0000 0000

# flags for function set
LCD_8BITMODE = 0x10     # 0001 0000
LCD_4BITMODE = 0x00     # 0000 0000
LCD_2LINE = 0x08        # 0000 1000
LCD_1LINE = 0x00        # 0000 0000
LCD_5x8DOTS = 0x00      # 0000 0000


class RGB1602:
    def __init__(self, col, row, loglevel: str='info', alertlog: str=False):
        
        ### Logger setup
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
        
        streamHandler = logging.StreamHandler()
        formatter = logging.Formatter(fmt='[%(asctime)s]-[%(name)s]-[%(levelname)s]: %(message)s', datefmt='%H:%M:%S')
        streamHandler.setFormatter(formatter)
        
        self.logger.addHandler(streamHandler)
        
        # Setup warn logging to file
        if alertlog:
            fileHandler = logging.FileHandler(alertlog)
            fileHandler.setFormatter(formatter)
            fileHandler.setLevel(logging.WARNING)
            self.logger.addHandler(fileHandler)
            self.logger.warning(f'Logging warnings to {alertlog}')
            
        self.logger.info(f'Logger setup finished for {__name__} module')
        ### Logger setup finished
        
        self._row = row
        self._col = col
        self._showfunction = LCD_4BITMODE | LCD_1LINE | LCD_5x8DOTS

        self.colors =  {
          'GREEN': (0,255,0),
          'YELLOW': (220,100,10),
          'RED' : (255,0,0),
          'WHITE' : (248,248,60),
          'YELLOW_GREEN' : (144,249,15),
          'MAX_WHITE': (255,255,255),
          'SCREEN_OFF': (0,0,0)
        }
        self.begin(self._row, self._col)

    # send a command to display data address
    def command(self, cmd):
        # Convert values to binary for logging purposes
        cmd_bin = format(cmd, '08b')
        cmd_bin = f'{cmd_bin[0:4]} {cmd_bin[4:8]}'
        self.logger.debug(f'Sending command [{cmd_bin}] to display')
        
        try:
            b.write_byte_data(LCD_ADDRESS, 0x80, cmd)
        except OSError as err:
            self.logger.error(err)

    # send a command to character creator address
    def write(self, data):
        
        # Handle special letters ä and ö, which are not in proper places (for latin-1) in the AiP31068-001 CHARACTER PATTERN of the board.
        if data == 228 :# ä
            data = 225 
        if data == 246: # ö
            data = 239 
        
        # Convert values to binary for logging purposes
        data_bin = format(data, '08b')
        data_bin = f'{data_bin[0:4]} {data_bin[4:8]}'
        self.logger.debug(f'Sending command [{data_bin}] to character creator')
        
        try:
            b.write_byte_data(LCD_ADDRESS, 0x40, data)
        except OSError as err:
            self.logger.error(err)

    def setReg(self, reg, data):
        # Convert values to binary for logging purposes
        data_bin = format(data, '08b')
        data_bin = f'{data_bin[0:4]} {data_bin[4:8]}'
        reg_bin = format(reg, '08b')
        reg_bin = f'{reg_bin[0:4]} {reg_bin[4:8]}'
        self.logger.debug(f'Sending command [{data_bin}] to RGB, registry [{reg_bin}]')
        
        try:
            b.write_byte_data(RGB_ADDRESS, reg, data)
        except OSError as err:
            self.logger.error(err)

    def setRGB(self, rgb:tuple):
        self.setReg(REG_RED, rgb[0])
        self.setReg(REG_GREEN, rgb[1])
        self.setReg(REG_BLUE, rgb[2])

    def setCursor(self, col, row):
        if(row == 0):
            col |= 0x80
        elif(row == 1):
            col |= 0xc0
        else:
            self.logger.error(f'Tried to write to invalid row {row}')
            raise Exception(f'Tried to write to invalid row {row}')
            
        self.command(col)

    def clear(self):
        self.command(LCD_CLEARDISPLAY)
        time.sleep(0.002)

    def printOnOneRow(self, arg, row):
        if(isinstance(arg, int)):
            arg = str(arg)
        self.setCursor(0, row)
        
        btarr = bytearray()
        
        for char in arg:
            try:
                btarr.extend(bytes(char, 'latin_1'))
            except UnicodeEncodeError:
                # Erroneous characters will be turned into '?'
                self.logger.error(f'Could not encode: {char}')
                btarr.extend(bytes('?', 'latin_1'))
        
        for bt in btarr:
            self.write(bt)

    # 126 → 0x7e
    # 127 ← 0x7f
    
    # Prints out every character in the board
    # Echoes their values in int, hex and what character it (possibly) represents
    # Characters printed to stdout are not necessarily the same as the ones on the board
    def printOutEveryCharacter(self):
        val = int("20", base=16)
        print(f'(INT) -> (HEXA) -> (CHAR)')
        for i in range(255):
            if (i%16 and i>0) == 0:
                if ((i/16) % 2) == 0:  
                    # Print to first row
                    self.setCursor(0, 0)
                else: 
                    # Change to second row
                    self.setCursor(0, 1)
            self.write(val)
            print(f'({str(val).zfill(3)}) -> ({hex(val)}) -> ( {chr(val)} )')
            val = val +1
            # time.sleep(.1)
            time.sleep(.5)
            if (i%32 and i>0) == 0:
                time.sleep(2)
                self.clear()
        print("Finished!")

    # Write letters one by one with a short interval.
    def sequentialWrite(self, msg:str, color:str='YELLOW_GREEN', turnOffAfter:bool=True, freezeFor:int=3, pauseOnPunct=True):
        """Prints a message, letter by letter.
        Pauses for 1 sec when character is '.'
        Pauses for .5 sec if the character is ','
        Whitespaces, if first character on a row, will be erased to screen space.

        Args:
            msg (str): [description]
            turnOffAfter (bool, optional): [description]. Defaults to True.
            freezeFor (int, optional): [description]. Defaults to 3.
        """
        
        self.clear()
        self.setRGB(self.colors[color])
        
        row = 0
        col = 0
        self.setCursor(col, row)
        
        try:
            b_array = bytearray(msg, encoding='latin_1', errors='replace')
        except UnicodeEncodeError as e:
            self.logger.error(e)
        for c in b_array:
            # Erase a whitespace, if its the first character on a row. Waste less screen space.
            if col == 0 and chr(c).isspace():
                col -= 1
            col += 1
            
            # if c is newline, change row
            if c == 10:
                if row == 0:
                    col = 0
                    row = 1
                elif row == 1:
                    col = 0
                    row = 0
            else:
                self.write(c)
            
            if pauseOnPunct:
                if chr(c) == '.':
                    time.sleep(1)
                elif chr(c) == ',':
                    time.sleep(.2)
            # char 10 is newline. We should wait for a bit
            if c == 10:
                time.sleep(1)
                # screen is full, let's erase
                if row == 0:
                    self.clear()
            if col > 15:
                col = 0
                if row == 0:
                    row = 1
                else:
                    row = 0
                    time.sleep(.3)
                    self.clear()
            time.sleep(.1)
            self.setCursor(col, row)
        
        time.sleep(freezeFor)
        if turnOffAfter:
            self.turnOff()
    
    # Print out one message and turn off screen
    def printOnTwoRows(self, argTopRow:str='', argBotRow:str='', color:str='YELLOW_GREEN', turnOffAfter:bool=True, freezeFor:int=2):
        """
            Print a message across the whole screen.

            Parameters
            ----------
            argTopRow : str
                Message to print on top row.
            argBotRow : str
                Message to print on bottow row.
            color : ENUM
                Message color. One of ['GREEN', 'YELLOW', 'RED', 'WHITE', 'YELLOW_GREEN']
            turnOffAfter: bool
                Defines if the screen should be turned off after displaying the message
            freezeFor: int
                Freeze the message on the screen (as in, sleep) for given amouNt of seconds.

            Examples
            --------
            >>> printOnTwoRows('Hello', 'world', color='YELLOW_GREEN', turnOffAfter=False, freezeFor=5)
            """
        try:
            self.clear()
            self.setRGB(self.colors[color])
            self.printOnOneRow(argTopRow, 0)
            self.printOnOneRow(argBotRow, 1)
            time.sleep(freezeFor)
            if turnOffAfter:
                self.clear()
                self.turnOff()
        except OSError as err:
            print(err)

    def display(self):
        self._showcontrol |= LCD_DISPLAYON
        self.command(LCD_DISPLAYCONTROL | self._showcontrol)

    def turnOff(self):
        
      self.setRGB(self.colors['SCREEN_OFF'])
    
    def flashScreen(self, color='YELLOW_GREEN', topRow='', botRow=''):
        self.printOnTwoRows(topRow, botRow, color=color, turnOffAfter=False, freezeFor=0)
        for i in range(4):
            self.setRGB(self.colors[color])
            time.sleep(.2)
            self.turnOff()
            time.sleep(.2)
        self.clear()

    def begin(self, cols, lines):
        if (lines > 1):
            self._showfunction |= LCD_2LINE

        self._numlines = lines
        self._currline = 0

        time.sleep(0.05)

        # Send function set command sequence
        self.command(LCD_FUNCTIONSET | self._showfunction)

        # delayMicroseconds(4500);  # wait more than 4.1ms
        time.sleep(0.005)

        # second try
        self.command(LCD_FUNCTIONSET | self._showfunction)

        # delayMicroseconds(150);
        time.sleep(0.005)

        # third go
        self.command(LCD_FUNCTIONSET | self._showfunction)

        # finally, set # lines, font size, etc.
        self.command(LCD_FUNCTIONSET | self._showfunction)

        # turn the display on with no cursor or blinking default
        self._showcontrol = LCD_DISPLAYON | LCD_CURSOROFF | LCD_BLINKOFF
        self.display()

        # clear it off
        self.clear()
        
        # Initialize to default text direction
        self._showmode = LCD_ENTRYLEFT | LCD_ENTRYSHIFTDECREMENT
        
        # set the entry mode
        self.command(LCD_ENTRYMODESET | self._showmode)

        # backlight init
        self.setReg(REG_MODE1, 0)
        
        # set LEDs controllable by both PWM and GRPPWM registers
        self.setReg(REG_OUTPUT, 0xFF)
        
        # set MODE2 values
        # 0010 0000 -> 0x20  (DMBLNK to 1, ie blinky mode)
        self.setReg(REG_MODE2, 0x20)

        self.setColorWhite()

    def setColorWhite(self):
        self.setRGB(self.colors['MAX_WHITE'])

    def readInput(self, color:str='YELLOW_GREEN'):
        self.getch = _Getch()
        self._showcontrol = LCD_CURSOROFF | LCD_BLINKON
        self.display()
        print("Press ESC to quit")
        self.clear()
        self.setRGB(self.colors[color])
        
        memory = []
        i = 0
        row = 0
        
        while True:
            # check if top row is full
            if i > 15 and row == 0:
                row = 1
                i = 0
            # prevent cursor going negative
            if i < 0:
                i = 0
            # if screen is full, clear it and go to start. unless user pressed backspace 0x7f
            if i == 15 and row == 1 and bytearr != b'\x7f':
                self.clear()
                row = 0
                i = 0
            
            self.setCursor(i, row)
            
            # get char from stdin
            c = self.getch.__call__()
            # convert to bytes 
            bytearr = bytearray(c, 'latin_1')
            # print(bytearr)
            
            # quit on ESC (0x1b) and CTRL+C (0x03)
            if bytearr == b'\x1b' or bytearr == b'\x03':
                self.sequentialWrite('Bye bye!', freezeFor=0)
                self._showcontrol = LCD_DISPLAYOFF | LCD_CURSOROFF | LCD_BLINKOFF
                self.display()
                self.clear()
                return False

            # character as int code
            x = bytearr[0]
                
            # Backspace
            if x == 127:
                # Clear character from memory
                if len(memory) != 0:
                    del memory[-1]
                
                # TODO: print memory on screen if it wraps multiple screenfuls.
                if row == 0 and i == 0 and len(memory) > 0:
                    # self.printOnTwoRows()
                    # self.sequentialWrite(''.join(memory), freezeFor=0, pauseOnPunct=False, turnOffAfter=False)
                    pass
                if i > 0:
                    i -= 1
                
                # move back to top row
                elif i == 0 and row == 1:
                    i = 15
                    row = 0
                
                # Walk cursor back, and overwrite with a space
                self.setCursor(i, row)
                x = 32 # int 32 is space
                self.write(x)
                # The cursor moves forward on its own after a write (?!), so lets set it back
                self.setCursor(i, row)
            
            # Enter is "send"
            elif x == 13:
                string = ''.join(memory)
                print(string)
                memory = []
                self.clear()
                i=0
                row=0
                return string
            
            else:
                memory.append(c)
                self.write(x)
                i += 1
                
            time.sleep(.01)
        
