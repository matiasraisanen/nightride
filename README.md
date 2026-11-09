# Nightride FM player
Text-based player for [Nightride FM](https://nightride.fm/) synthwave radio.

![](./images/player.gif)  
In this screenshot I am running the player on [cool-retro-term](https://github.com/Swordfish90/cool-retro-term) to give it a bit more retro flavour.  
The player should work on the terminal emulator of your choice however.


## Code

[NightrideAPI.py](./NightrideAPI.py)  
Handles communication with the web audio stream and audio player.


[Radio.py](./Radio.py)  
Text interface for radio. Handles user input and communicates that to the API.


[AudioPlayer.py](./AudioPlayer.py)  
Handles audio player functionality using VLC


[LevelMeter.py](./LevelMeter.py)  
Measures the audio level of the stream for the VU meter


[audio_streams.py](./audio_streams.py)  
Finds the player's own audio stream in PulseAudio or PipeWire


[screen.py](./screen.py)  
Draws the interface on the terminal, sending only what changed


[settings.py](./settings.py)  
Reads and saves settings.ini, with defaults for anything missing


[settings.ini](./settings.ini)  
Various settings for the player


[paths.py](./paths.py)  
Locations of the settings and log files, so the player can be started from any directory.

## How to start
Works on Linux and Windows. It needs [VLC](https://www.videolan.org/vlc/) for playing the audio.

### Linux

0. Install dependencies:

        sudo apt update && sudo apt install vlc

        python3 -m venv .venv
        .venv/bin/pip install -r requirements.txt

1. Run Radio.py:

        .venv/bin/python Radio.py

### Windows

0. Install [VLC](https://www.videolan.org/vlc/). It has to be the 64-bit version if your Python is 64-bit.

1. Install the Python dependencies:

        py -m venv .venv
        .venv\Scripts\pip install -r requirements.txt

2. Run Radio.py in [Windows Terminal](https://aka.ms/terminal):

        .venv\Scripts\python Radio.py

The VU meter and the NO AUDIO OUTPUT warning only work on Linux for now.


## How to use

The interface is modelled after MS-DOS era applications, with pull-down menus and dialog boxes.

Press **F10** to open the menus. **Alt** and the red letter of a menu opens it directly: **Alt-R** for *Radio*, **Alt-O** for *Options*, **Alt-T** for *Theme*.  
In the menus, use the arrow keys to move, **ENTER** to choose and **ESC** to close. Red letters in menu items are hotkeys.

- *Radio*: Browse stations, Help, About, Exit
- *Options*: Mute, VU meter, Clock, and Settings for the default station, default theme and startup volume
- *Theme*: the color scheme
  - *Synthwave*: purple and cyan on dark grey (the default)
  - *Outrun*: neon pink, orange and yellow on navy
  - *Darksynth*: blood red and grey on black
  - *DOS*: the classic blue MS-DOS look
  - *C64*: light blue on dark blue, like a Commodore 64
  - *Amber CRT* and *Green CRT*: single-colour monitors

Press **F1** for help, which lists all the keys.

Press **F2** to browse the stations.  
Use arrow keys **UP** and **DOWN** to choose station, and press **ENTER** to play it.  
Arrow keys **LEFT** and **RIGHT** switch between the *Play* and *Cancel* buttons, and **ESC** cancels.  
Stations can also be changed using numbers **1** through **9** on the main screen,  
or with arrow keys **LEFT** and **RIGHT** to go to the previous or next station.

Press arrow keys **UP** and **DOWN** to change volume, and **m** to mute.

Press **v** to enable/disable the VU meter. It shows the average level of the music for the left and right channels. A single lit segment marks the highest point the bar reached recently.

Press **Alt-X** or **F12** to quit, or **ESC** to get asked first.

## Notes

The player looks best in an 80 by 25 terminal, like in the old days. It needs at least 50 columns by 14 rows, or 16 with the VU meter on.  
If your terminal uses Esc, F10 or other keys for its own actions, those keys won't reach the player. Unbind them in the terminal's settings.  
The VU meter needs `parec` and `pactl`, which come with PulseAudio and PipeWire (package `pulseaudio-utils` on Debian and Ubuntu).  
It measures the music itself, so the volume setting doesn't change it, but it drops to zero while muted.  
On terminals with true colour, like Konsole and Windows Terminal, the themes show their exact colours regardless of your terminal's colour theme. Other terminals get the closest colours they have.

If the stream drops, the player reconnects by itself and shows **RECONNECTING** meanwhile. **STREAM ERROR** means it has failed several times in a row, but it keeps trying. **NO SONG INFO** means the song information can't be fetched right now. The music may still play.

If the player shows **NO AUDIO OUTPUT**, its sound isn't reaching your sound server. This can happen when PipeWire gets stuck, for example after suspend or after unplugging a dock. Restarting it usually helps:

    systemctl --user restart wireplumber pipewire pipewire-pulse
