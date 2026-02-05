"""Main Textual application for Nightride FM."""

import time

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Header, Footer

from .api import Config, NightrideClient, StationMetadata
from .widgets import RadioDisplay, MenuBar
from .modals import AboutModal, StationModal


class NightrideApp(App):
    """Nightride FM TUI Application."""

    TITLE = "Nightride FM"

    CSS = """
    Screen {
        background: $surface;
    }
    #main-container {
        margin: 1 2;
    }
    RadioDisplay {
        height: 7;
    }
    MenuBar {
        height: 1;
        margin: 1 0 0 0;
        text-align: center;
    }
    """

    BINDINGS = [
        Binding("1", "station('1')", "Station 1", show=False),
        Binding("2", "station('2')", "Station 2", show=False),
        Binding("3", "station('3')", "Station 3", show=False),
        Binding("4", "station('4')", "Station 4", show=False),
        Binding("5", "station('5')", "Station 5", show=False),
        Binding("6", "station('6')", "Station 6", show=False),
        Binding("7", "station('7')", "Station 7", show=False),
        Binding("8", "station('8')", "Station 8", show=False),
        Binding("9", "station('9')", "Station 9", show=False),
        Binding("plus", "volume_up", "Volume Up", show=False),
        Binding("minus", "volume_down", "Volume Down", show=False),
        Binding("v", "toggle_vu", "Toggle VU", show=False),
        Binding("f1", "show_about", "About"),
        Binding("f2", "show_stations", "Stations"),
        Binding("f12", "quit", "Quit"),
    ]

    def __init__(self):
        super().__init__()
        self.config = Config.load()
        self.client = NightrideClient(self.config)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="main-container"):
            yield RadioDisplay(id="radio-display")
            yield MenuBar()
        yield Footer()

    def on_mount(self) -> None:
        """Initialize the application."""
        # Start the client
        self.client.start()
        self.client.add_metadata_callback(self._on_metadata_update)

        # Set initial UI state
        display = self.query_one(RadioDisplay)
        display.vu_enabled = self.config.vu_meter
        self._update_station_display()
        self._update_volume_display()

        # Start periodic updates
        self.set_interval(0.1, self._periodic_update)

    def on_unmount(self) -> None:
        """Cleanup on exit."""
        # Save VU meter preference
        try:
            display = self.query_one(RadioDisplay)
            self.config.vu_meter = display.vu_enabled
            self.config.save()
        except Exception:
            pass  # Widget may not exist during shutdown

        # Stop client
        self.client.stop()

    def _periodic_update(self) -> None:
        """Periodic UI updates."""
        try:
            display = self.query_one(RadioDisplay)
        except Exception:
            return  # Widget not available (e.g., modal is open)

        # Refresh VU meter animation
        if display.vu_enabled:
            display.refresh()

        # Update playtime
        metadata = self.client.get_current_metadata()
        if metadata.started_at > 0:
            elapsed = int(time.perf_counter() - metadata.started_at)
            display.set_elapsed(elapsed)

    def _on_metadata_update(self, station: str, metadata: StationMetadata) -> None:
        """Handle metadata updates from the API."""
        # Only update if this is the current station
        if station == self.client.get_current_station():
            self.call_from_thread(self._update_now_playing, metadata)

    def _update_now_playing(self, metadata: StationMetadata) -> None:
        """Update the now playing display."""
        display = self.query_one(RadioDisplay)
        display.update_metadata(metadata.artist, metadata.song)

    def _update_station_display(self) -> None:
        """Update the station display."""
        station = self.client.get_current_station()
        if station:
            num = self.client.get_station_number(station) or "?"
            self.query_one(RadioDisplay).update_station(num, station)

    def _update_volume_display(self) -> None:
        """Update the volume slider."""
        self.query_one(RadioDisplay).set_volume(self.client.audio.volume)

    # Actions

    def action_station(self, num: str) -> None:
        """Switch to a station by number."""
        station = self.client.play_station_by_number(num)
        if station:
            self._update_station_display()
            # Update now playing for new station
            metadata = self.client.get_current_metadata()
            self._update_now_playing(metadata)

    def action_volume_up(self) -> None:
        """Increase volume."""
        self.client.audio.volume += 1
        self._update_volume_display()

    def action_volume_down(self) -> None:
        """Decrease volume."""
        self.client.audio.volume -= 1
        self._update_volume_display()

    def action_toggle_vu(self) -> None:
        """Toggle VU meter."""
        self.query_one(RadioDisplay).toggle_vu()

    def action_show_about(self) -> None:
        """Show the about modal."""
        self.push_screen(AboutModal())

    def action_show_stations(self) -> None:
        """Show the station selector modal."""
        modal = StationModal(
            stations=self.config.stations,
            current_station=self.client.get_current_station(),
            get_metadata=self.client.metadata.get_metadata,
        )
        self.push_screen(modal, callback=self._on_station_selected)

    def _on_station_selected(self, station: str | None) -> None:
        """Handle station selection from modal."""
        if station:
            self.client.play_station(station)
            self._update_station_display()
            metadata = self.client.get_current_metadata()
            self._update_now_playing(metadata)


def main():
    """Entry point for the application."""
    app = NightrideApp()
    app.run()


if __name__ == "__main__":
    main()
