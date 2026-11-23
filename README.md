# Nightride

A terminal player for [Nightride FM](https://nightride.fm/) synthwave radio, in the style of the MS-DOS programs of the early 90s: pull-down menus, dialog boxes and drop shadows, in a terminal window.

![The player: the main screen, the theme preview, browsing the stations and changing the volume](./images/player.gif)

This is an unofficial player, not made by Nightride FM. The music and the song info come from their public streams.

## Features

- All the Nightride FM stations: nightride, chillsynth, datawave, spacesynth, darksynth, horrorsynth and ebsm
- The song playing now, and the songs played during the last hour
- Web search for a song on Bandcamp, YouTube or Google
- A stereo VU meter that measures the music itself
- Seven colour themes, from synthwave neon to a green CRT monitor
- Works with the keyboard and the mouse
- Linux and Windows, with a stand-alone version for Windows that needs nothing installed

## Install

### Windows

1. Download `nightride-windows.zip` from the [latest release](https://github.com/matiasraisanen/nightride/releases/latest).
2. Unzip it anywhere, and keep the files together.
3. Double-click `nightride.exe`, or run `nightride` in that folder from cmd.exe or PowerShell.

Python and VLC are included, so nothing else needs to be installed. It looks best in [Windows Terminal](https://aka.ms/terminal), the default terminal on Windows 11.

### Linux

The player needs [VLC](https://www.videolan.org/vlc/) for the audio, and [uv](https://docs.astral.sh/uv/) to install it.

1. Install VLC. On Debian and Ubuntu:

       sudo apt update && sudo apt install vlc

2. Install the player as the `nightride` command:

       uv tool install git+https://github.com/matiasraisanen/nightride

3. Run it from any terminal:

       nightride

### From source

To change the code, clone the repository and install it from the project folder with `--editable`. The command then runs the code in that folder, so changes show up without reinstalling:

    uv tool install --editable .

Or run it without installing, in a virtual environment:

    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
    .venv/bin/python radio.py

On Windows, this needs VLC installed, and 64-bit VLC if your Python is 64-bit.

### Command line

| Option | What it does |
|---|---|
| `--test-stream [STATION]` | Plays a station for a few seconds without the interface, and says whether it worked |
| `--debug` | Logs every key press and more, for finding bugs |
| `--version` | Shows the version |

## How to use

Use the keys below, or the menus: press **F10**, or **Alt** and the red letter of a menu, like **Alt-R** for *Radio*. **F1** shows all the keys in the player.

### Main screen

| Key | What it does |
|---|---|
| **←** **→** or **1**–**7** | Change station |
| **↑** **↓** | Volume in steps of 10 |
| **Shift**-**↑** **↓** | Volume in steps of 1 |
| **M** | Mute |
| **F2** | Browse the stations |
| **F3** | Recently played songs |
| **W** | Search the web for the song |
| **V** | VU meter on or off |
| **C**, **D** | Clock, date on or off |
| **T**, **Shift**-**T** | Next, previous theme |
| **F10** | Menus |
| **F1** | Help |
| **Esc** | Exit, after asking |
| **Alt-X**, **F12** | Exit right away |

In the menus and dialogs, the arrow keys and **Tab** move, **Enter** chooses and **Esc** closes.

### Menus

- *Radio*: Browse stations, Recently played, Web search, Mute, Exit
- *Options*: VU meter, Clock, Date, Mouse, and *Settings*
- *Theme*: the colour themes. The highlighted theme shows right away. **Enter** keeps it, and **Esc** goes back to the one you had.
  - *Synthwave*: purple and cyan on dark grey (the default)
  - *Outrun*: neon pink, orange and yellow on navy
  - *Darksynth*: blood red and grey on black
  - *DOS*: the classic blue MS-DOS look
  - *C64*: light blue on dark blue, like a Commodore 64
  - *Amber CRT* and *Green CRT*: single-colour monitors
- *Help*: Keys, the Nightride.fm website, and About

*Settings* has the station and volume to start with (by default the ones you used last), the clock and date formats, and which messages to show.

### Mouse

- Click the menus, the buttons and the key hints on the bottom line.
- In *Browse* and *Recently played*, click to pick a row, and double-click to play the station or search for the song.
- On the main screen, click the station to browse, and the artist or song to search the web. Click the volume bar to set the volume, the arrows next to it to step by 10, and the number to mute.
- The scroll wheel changes the volume on the main screen, and scrolls the lists.

While the player has the mouse, most terminals select text with **Shift** held down. *Options* → *Mouse* turns the mouse off.

### Messages

A message above the bottom line says what a key did, and shows each new song. *Settings* → *Notifications* chooses which ones show. Errors always show.

The song and the station are also in the terminal's window title. Some terminals, like Konsole, only show titles set by programs if their tab title format includes `%w`.

## Settings and files

| | Linux | Windows |
|---|---|---|
| Settings | `~/.config/nightride/settings.ini` | `%APPDATA%\nightride\settings.ini` |
| Log | `~/.local/state/nightride/radio.log` | `%APPDATA%\nightride\radio.log` |
| Recently played | `~/.local/state/nightride/history.json` | `%APPDATA%\nightride\history.json` |

The settings start as a copy of [settings.ini](./settings.ini). Most of them can be changed in the player, but the file can also be edited by hand while the player is closed:

| Setting | |
|---|---|
| `default_station` | Station to start on, or `last` for the one played last |
| `start_volume` | Volume to start with, 0 to 99, or `last` for the one used last |
| `clock_format`, `date_format` | [strftime formats](https://strftime.org) for the clock and date |
| `notifications` | `all`, `off`, or `songs`, `actions`, or both separated by a comma |
| `theme` | One of the theme names |
| `vu_meter`, `clock`, `date`, `mouse` | `True` or `False` |
| `[STATIONS]` | The stations and their number keys |
| `[URLS]` | The stream and song info addresses, the website, and the web search addresses. `{query}` is replaced with the song. |

The log is kept across restarts, with each start and exit marked. It keeps the last day, and at most about 1 MB. Recently played songs are kept for an hour after the player is closed.

## Troubleshooting

- **No sound:** `nightride --test-stream` plays a station without the interface, and says whether it worked. The log may say more.
- **A key does nothing:** the terminal may use it for something of its own, like **F10** or **Esc**. Unbind it in the terminal's settings, or use the menus.
- **NO AUDIO OUTPUT:** VLC is playing but can't reach the sound system, for example when PipeWire is stuck. This warning only works on Linux for now.
- **The VU meter says it needs something:** on Linux, it needs `parec` and `pactl`, which come with PulseAudio and PipeWire (package `pulseaudio-utils` on Debian and Ubuntu).
- **Clicks select text in cmd.exe:** the player turns off QuickEdit while it runs, so clicks reach it. If they still select text, turn QuickEdit off in the window's properties.
- **The window is too small:** the player needs at least 50 columns by 14 rows, or 16 with the VU meter on. It looks best at 80 by 25, like in the old days.

The themes show their exact colours in terminals with true colour, like Konsole and Windows Terminal. Other terminals get the closest colours they have.

On Linux, the VU meter records the player's own audio from PulseAudio or PipeWire, and shows its average level. On Windows, it reads the same meter as the Windows volume mixer. That meter gives the loudest samples rather than the average, so the player takes 9 dB off them to read like the Linux meter. Both measure the music itself, so the volume doesn't change them, but they drop to zero while muted.

## Building the Windows version

On Windows, with [uv](https://docs.astral.sh/uv/) or 64-bit Python installed, in the project folder:

    powershell -ExecutionPolicy Bypass -File windows\build.ps1

It downloads VLC, checks it, and packs the player, Python and VLC together with [PyInstaller](https://pyinstaller.org/). The result is in `dist\nightride\`, and zipped as `dist\nightride-windows.zip`.

## Code

| File | |
|---|---|
| [radio.py](./radio.py) | The interface: drawing the screens, keys, mouse and menus |
| [screen.py](./screen.py) | Draws on the terminal, sending only what changed |
| [nightride_api.py](./nightride_api.py) | Reads the song info stream, and keeps the recently played songs |
| [audio_player.py](./audio_player.py) | Plays the audio streams with VLC, and reconnects when they drop |
| [level_meter.py](./level_meter.py) | Measures the audio level for the VU meter |
| [audio_streams.py](./audio_streams.py) | Finds the player's own audio stream in PulseAudio or PipeWire |
| [win_audio.py](./win_audio.py) | Finds the player's own audio session on Windows, and reads its level |
| [settings.py](./settings.py) | Reads and saves settings.ini, with defaults for anything missing |
| [paths.py](./paths.py) | Where the settings, log and history files go |
| [logger.py](./logger.py) | Logging, with old entries trimmed away |
| [windows/](./windows/) | The Windows build |

## License

[GPL-3.0](./LICENSE). The Windows version includes [VLC](https://www.videolan.org/), licensed under the GNU LGPL and GPL.
