# Nightride FM player
Text-based player for [Nightride FM](https://nightride.fm/) synthwave radio.

![](./images/player.gif)


## Project structure

[NightrideAPI.py](./NightrideAPI.py)  
Handles pretty much all the internal operations. This is what glues the Nightride.fm and my player together


[Radio.py](./Radio.py)  
Text interface for radio. Handles user input, and calls the API accordinly.


[AudioPlayer.py](./AudioPlayer.py)  
Handles audio player functionality using VLC


[Nightride.ini](./Nightride.ini)  
Various settings for the player

[RGB1602.py](./RGB1602.py)  
Controller for optional [Waveshare RGB1602](https://www.waveshare.com/wiki/LCD1602_RGB_Module) LCD module.

## How to use

0. Install dependencies:

        pip3 install python-vlc sseclient-py

1. Run Radio.py:

        python3 Radio.py
