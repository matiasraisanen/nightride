Nightride FM player for Windows
===============================

Double-click nightride.exe, or run it from cmd.exe or PowerShell:

    nightride

It looks best in Windows Terminal, the default terminal on Windows 11.
Nothing needs to be installed: Python and VLC are included in this folder.
Keep the files together. To start it from anywhere, add this folder to your PATH.

If there is no sound, run this to test the audio without the interface:

    nightride --test-stream

Settings: %APPDATA%\nightride\settings.ini
Log:      %APPDATA%\nightride\radio.log

The VU meter only works on Linux.

Includes VLC (https://www.videolan.org/), licensed under the GNU LGPL / GPL.
See _internal\vlc\VLC-COPYING.txt.
