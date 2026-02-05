"""Nightride FM API - SSE metadata streaming and audio playback."""

import configparser
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Optional

import sseclient
import urllib3
import vlc


@dataclass
class StationMetadata:
    """Metadata for a station's current track."""
    artist: str = ""
    song: str = ""
    started_at: float = 0.0


@dataclass
class Config:
    """Application configuration."""
    sse_url: str = "https://nightride.fm/meta"
    audio_base_url: str = "https://stream.nightride.fm"
    stations: Dict[str, str] = field(default_factory=dict)
    default_station: str = "chillsynth"
    vu_meter: bool = False
    max_retries: int = 3
    retry_delay: int = 5
    keepalive_timeout: int = 90

    @classmethod
    def load(cls, path: str = "settings.ini") -> "Config":
        """Load configuration from INI file."""
        config = configparser.ConfigParser()
        config.read(path)

        stations = {}
        if config.has_section("STATIONS"):
            for key, value in config.items("STATIONS"):
                stations[key] = value

        return cls(
            sse_url=config.get("URLS", "sse_url", fallback=cls.sse_url),
            audio_base_url=config.get("URLS", "audio_stream_base_url", fallback=cls.audio_base_url),
            stations=stations or {str(i): name for i, name in enumerate([
                "nightride", "chillsynth", "darksynth", "horrorsynth",
                "spacesynth", "datawave", "ebsm", "rektory", "rekt"
            ], 1)},
            default_station=config.get("SETTINGS", "default_station", fallback=cls.default_station),
            vu_meter=config.getboolean("SETTINGS", "vu_meter", fallback=cls.vu_meter),
            max_retries=config.getint("SETTINGS", "max_retries", fallback=cls.max_retries),
            retry_delay=config.getint("SETTINGS", "retry_delay", fallback=cls.retry_delay),
            keepalive_timeout=config.getint("SETTINGS", "keepalive_timeout", fallback=cls.keepalive_timeout),
        )

    def save(self, path: str = "settings.ini") -> None:
        """Save configuration to INI file."""
        config = configparser.ConfigParser()

        config["ADDONS"] = {"lcd1602": "False"}
        config["URLS"] = {
            "sse_url": self.sse_url,
            "audio_stream_base_url": self.audio_base_url,
        }
        config["STATIONS"] = self.stations
        config["SETTINGS"] = {
            "vu_meter": str(self.vu_meter),
            "default_station": self.default_station,
            "max_retries": str(self.max_retries),
            "retry_delay": str(self.retry_delay),
            "keepalive_timeout": str(self.keepalive_timeout),
        }

        with open(path, "w") as f:
            config.write(f)


class AudioPlayer:
    """VLC-based audio player for streaming radio."""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self._instance = vlc.Instance("--input-repeat=-1", "-q")
        self._player = self._instance.media_player_new()
        self._volume = 4  # 0-9 scale
        self._current_station: Optional[str] = None

    @property
    def volume(self) -> int:
        """Get current volume (0-9 scale)."""
        return self._volume

    @volume.setter
    def volume(self, value: int) -> None:
        """Set volume (0-9 scale)."""
        self._volume = max(0, min(9, value))
        # Convert to VLC's 0-100 scale (each step is ~11%)
        vlc_volume = min(self._volume * 11, 100)
        self._player.audio_set_volume(vlc_volume)

    @property
    def current_station(self) -> Optional[str]:
        """Get currently playing station."""
        return self._current_station

    def play(self, station: str) -> None:
        """Play a station stream."""
        url = f"{self.base_url}/{station}.m4a"
        media = self._instance.media_new(url)
        self._player.set_media(media)
        self._player.play()
        self._current_station = station
        # Restore volume after media change
        self.volume = self._volume

    def stop(self) -> None:
        """Stop playback."""
        self._player.stop()
        self._current_station = None

    def is_playing(self) -> bool:
        """Check if currently playing."""
        return self._player.is_playing() == 1


class MetadataService:
    """SSE-based metadata streaming service."""

    def __init__(
        self,
        url: str,
        on_update: Optional[Callable[[str, StationMetadata], None]] = None,
        max_retries: int = 3,
        retry_delay: int = 5,
        keepalive_timeout: int = 90,
    ):
        self.url = url
        self.on_update = on_update
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.keepalive_timeout = keepalive_timeout

        self._metadata: Dict[str, StationMetadata] = {}
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the metadata streaming thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._stream_worker, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the metadata streaming thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)

    def get_metadata(self, station: str) -> StationMetadata:
        """Get metadata for a station."""
        with self._lock:
            return self._metadata.get(station, StationMetadata())

    def _stream_worker(self) -> None:
        """Worker thread for SSE streaming."""
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        while not self._stop_event.is_set():
            try:
                self._connect_and_stream()
            except Exception:
                if not self._stop_event.is_set():
                    time.sleep(self.retry_delay)

    def _connect_and_stream(self) -> None:
        """Connect to SSE and process events."""
        http = urllib3.PoolManager(cert_reqs="CERT_NONE", assert_hostname=False)
        headers = {"Accept": "text/event-stream"}

        for attempt in range(self.max_retries):
            try:
                response = http.request(
                    "GET", self.url, preload_content=False, headers=headers
                )
                client = sseclient.SSEClient(response)
                self._process_events(client)
                break
            except Exception:
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                else:
                    raise

    def _process_events(self, client: sseclient.SSEClient) -> None:
        """Process SSE events."""
        keepalive_timer = None

        def reset_timer():
            nonlocal keepalive_timer
            if keepalive_timer:
                keepalive_timer.cancel()
            keepalive_timer = threading.Timer(
                self.keepalive_timeout,
                lambda: None  # Will cause reconnect on timeout
            )
            keepalive_timer.start()

        reset_timer()

        try:
            for event in client.events():
                if self._stop_event.is_set():
                    break

                if event.data == "keepalive":
                    reset_timer()
                else:
                    self._parse_and_update(event.data)
        finally:
            if keepalive_timer:
                keepalive_timer.cancel()

    def _parse_and_update(self, data: str) -> None:
        """Parse event data and update metadata."""
        try:
            parsed = json.loads(data)
            if not parsed:
                return

            entry = parsed[0]
            station = entry.get("station", "")

            # Handle "rekt" stations differently (artist - title format)
            if "rekt" in station:
                match = re.search(r"(.+)\s-\s(.+)", entry.get("title", ""))
                if match:
                    artist, song = match.group(1), match.group(2)
                else:
                    artist, song = "", entry.get("title", "")
            else:
                artist = entry.get("artist", "")
                song = entry.get("title", "")

            metadata = StationMetadata(
                artist=artist,
                song=song,
                started_at=time.perf_counter(),
            )

            with self._lock:
                self._metadata[station] = metadata

            if self.on_update:
                self.on_update(station, metadata)

        except (json.JSONDecodeError, KeyError, IndexError):
            pass


class NightrideClient:
    """Main client combining audio playback and metadata streaming."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config.load()
        self.audio = AudioPlayer(self.config.audio_base_url)
        self.metadata = MetadataService(
            url=self.config.sse_url,
            on_update=self._on_metadata_update,
            max_retries=self.config.max_retries,
            retry_delay=self.config.retry_delay,
            keepalive_timeout=self.config.keepalive_timeout,
        )
        self._metadata_callbacks: list[Callable[[str, StationMetadata], None]] = []

    def start(self) -> None:
        """Start the client services."""
        self.metadata.start()
        # Play default station
        self.play_station(self.config.default_station)

    def stop(self) -> None:
        """Stop all client services."""
        self.metadata.stop()
        self.audio.stop()

    def play_station(self, station: str) -> None:
        """Play a station by name."""
        self.audio.play(station)

    def play_station_by_number(self, number: str) -> Optional[str]:
        """Play a station by number key (1-9). Returns station name or None."""
        station = self.config.stations.get(number)
        if station:
            self.play_station(station)
        return station

    def get_station_name(self, number: str) -> Optional[str]:
        """Get station name by number."""
        return self.config.stations.get(number)

    def get_station_number(self, name: str) -> Optional[str]:
        """Get station number by name."""
        for num, station in self.config.stations.items():
            if station == name:
                return num
        return None

    def get_current_station(self) -> Optional[str]:
        """Get currently playing station name."""
        return self.audio.current_station

    def get_current_metadata(self) -> StationMetadata:
        """Get metadata for currently playing station."""
        station = self.audio.current_station
        if station:
            return self.metadata.get_metadata(station)
        return StationMetadata()

    def add_metadata_callback(self, callback: Callable[[str, StationMetadata], None]) -> None:
        """Add a callback for metadata updates."""
        self._metadata_callbacks.append(callback)

    def _on_metadata_update(self, station: str, metadata: StationMetadata) -> None:
        """Handle metadata updates."""
        for callback in self._metadata_callbacks:
            try:
                callback(station, metadata)
            except Exception:
                pass
