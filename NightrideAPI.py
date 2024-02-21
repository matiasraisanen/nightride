import configparser
import json
import logging
import re
import sseclient
import urllib3
import time
import threading
from logger import Logger

from AudioPlayer import AudioPlayer


class NightRideAPI:
    def __init__(self, loglevel=logging.INFO, logfile: str = "radio.log"):
        ### Read config ###
        config = configparser.ConfigParser()
        config.read("settings.ini")

        self.logger = Logger(
            module_name=__name__,
            log_file=logfile,
            log_level=loglevel,
            delete_old_logfile=True,
            streamhandler=False,
            filehandler=True,
        )

        self.SSE_URL = config["URLS"]["sse_url"]
        AUDIO_STREAM_BASE_URL = config["URLS"]["audio_stream_base_url"]

        stationlist = config.items("STATIONS")
        self.stations = []
        for key, value in stationlist:
            self.stations.append(value)

        # Initialize SSE client
        self.init_client(self.SSE_URL)

        # Initialize audio player
        self.audioPlayer = AudioPlayer(
            base_url=AUDIO_STREAM_BASE_URL, loglevel=loglevel
        )

        for x in self.stations:
            self.logger.log.debug(f"Station {self.stations.index(x)}: {x}")

        self.station = "chillsynth"
        self.now_playing = {}
        self.audioPlayer.play(self.station)

        thread_1 = threading.Thread(target=self.start)
        thread_1.daemon = True
        thread_1.start()

    def start(self):
        self.get_metadata()

    def fetch_sse(self, url, headers):
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        http = urllib3.PoolManager(cert_reqs="CERT_NONE", assert_hostname=False)
        try:
            return http.request("GET", url, preload_content=False, headers=headers)
        except Exception as e:
            self.logger.log.error("fetch_sse error")
            self.logger.log.error(e)

    def init_client(self, sse_url):
        self.logger.log.debug(f"Start SSE client")
        headers = {"Accept": "text/event-stream"}
        try:
            self.response = self.fetch_sse(sse_url, headers)
            self.client = sseclient.SSEClient(self.response)
        except Exception as e:
            self.logger.log.error("init_client error")
            self.logger.log.error(e)

    def keep_sse_client_alive(self):
        self.logger.log.error(
            "Keepalive event not received in time. Restarting sse client."
        )
        self.client.close()
        self.init_client(self.SSE_URL)

        metadata_handler_thread = threading.Thread(target=self.start)
        metadata_handler_thread.daemon = True
        metadata_handler_thread.start()

    def get_metadata(self):
        countdown_seconds = 90
        # We could use a while true -loop here to ensure the event listener is restarted in case of an error.
        # while True:
        try:
            # Start a timer to keep SSE connection alive
            keep_alive_timer = threading.Timer(
                countdown_seconds, self.keep_sse_client_alive
            )

            for event in self.client.events():
                self.logger.log.debug(f"SSE event received: {event.data}")

                if event.data == "keepalive":
                    # Keepalive events should be received every {countdown_seconds}.
                    # We wait for {countdown_seconds} to pass, after which we assume the connection has been dropped, and we need to restart it.
                    self.logger.log.debug(
                        f"Keepalive detected, resfreshing {countdown_seconds}sec keepalive timer"
                    )
                    keep_alive_timer.cancel()
                    keep_alive_timer = threading.Timer(
                        countdown_seconds, self.keep_sse_client_alive
                    )
                    keep_alive_timer.start()

                elif event.data != "keepalive":
                    # Event can contain undefined values. Thus we need to initiate them as empty strings.
                    artist = ""
                    title = ""
                    station = ""

                    data = json.loads(event.data)
                    if "station" in data[0]:
                        station = data[0]["station"]
                    station = data[0]["station"]

                    # start_time is used to *estimate* play time on the interface
                    start_time = time.perf_counter()

                    if "rekt" in data[0]["station"]:
                        # Stations 'rekt' and 'rektory' have both the song title and the artist name in the 'title' section.
                        # These stations have to be handled in a different manner.
                        pattern = "(.+)\s-\s(.+)"
                        match = re.search(pattern, data[0]["title"])
                        if match:
                            artist = match.group(1)
                            title = match.group(2)
                        else:
                            if "title" in data[0]:
                                title = data[0]["title"]
                    else:
                        if "artist" in data[0]:
                            artist = data[0]["artist"]
                        if "title" in data[0]:
                            title = data[0]["title"]

                    current = {
                        "artist": artist,
                        "song": title,
                        "started_at": start_time,
                    }
                    self.now_playing[station] = current
                    self.logger.log.debug(
                        f"New song detected on {station}: {artist} - {title}"
                    )

        except Exception as e:
            self.logger.log.error("get_metadata error")
            self.logger.log.error(e)


if __name__ == "__main__":
    nightRide = NightRideAPI(loglevel=logging.DEBUG)
    try:
        nightRide.start()
    except KeyboardInterrupt:
        nightRide.audioPlayer.stop()
