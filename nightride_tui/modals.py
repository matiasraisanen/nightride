"""Modal screens for the Nightride FM TUI."""

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Static
from textual.binding import Binding

from . import __version__


class AboutModal(ModalScreen[None]):
    """About information modal."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("enter", "dismiss", "Close"),
        Binding("f1", "dismiss", "Close"),
    ]

    DEFAULT_CSS = """
    AboutModal {
        align: center middle;
    }
    AboutModal > Container {
        width: 52;
        height: 14;
        border: solid cyan;
        background: $surface;
        padding: 1;
    }
    AboutModal .title {
        text-align: center;
        text-style: bold;
        color: white;
        background: $primary;
        margin-bottom: 1;
    }
    AboutModal .footer {
        margin-top: 1;
        text-align: center;
    }
    """

    def compose(self) -> ComposeResult:
        with Container():
            yield Static(">> ABOUT <<", classes="title")
            yield Static("[cyan]AUTHOR:[/cyan]  [magenta]Matias Räisänen 2022[/magenta]")
            yield Static("[cyan]CONTACT:[/cyan] [magenta]matias@matiasraisanen.com[/magenta]")
            yield Static("[cyan]SOURCE:[/cyan]  [magenta]github.com/matiasraisanen/nightride[/magenta]")
            yield Static(f"[cyan]VERSION:[/cyan] [magenta]{__version__}[/magenta]")
            yield Static("")
            yield Static("Player for Nightride.fm")
            yield Static("(https://nightride.fm)")
            yield Static("")
            yield Static("[green]ENTER/ESC: [OK][/green]", classes="footer")


class StationModal(ModalScreen[str | None]):
    """Station selection modal."""

    BINDINGS = [
        Binding("escape", "cancel", "Close"),
        Binding("f2", "cancel", "Close"),
        Binding("enter", "select", "Select"),
        Binding("up", "move_up", "Up"),
        Binding("down", "move_down", "Down"),
    ]

    DEFAULT_CSS = """
    StationModal {
        align: center middle;
    }
    StationModal > Container {
        width: 52;
        height: 16;
        border: solid cyan;
        background: $surface;
        padding: 1;
    }
    StationModal .title {
        text-align: center;
        text-style: bold;
        color: white;
        background: $primary;
        margin-bottom: 1;
    }
    StationModal .station-list {
        height: 3;
        margin: 1 0;
    }
    StationModal .station-prev, StationModal .station-next {
        text-align: center;
        color: $text-muted;
    }
    StationModal .station-current {
        text-align: center;
        text-style: bold;
        color: cyan;
        background: $primary-darken-2;
    }
    StationModal .footer {
        margin-top: 1;
        text-align: center;
    }
    """

    selected_index: reactive[int] = reactive(0)

    def __init__(
        self,
        stations: dict[str, str],
        current_station: str | None = None,
        get_metadata=None,
    ):
        super().__init__()
        self.stations = stations
        self._station_list = list(stations.values())
        self.get_metadata = get_metadata
        self._mounted = False

        # Set initial selection to current station
        if current_station and current_station in self._station_list:
            self.selected_index = self._station_list.index(current_station)

    def compose(self) -> ComposeResult:
        with Container():
            yield Static(">> SELECT STATION <<", classes="title")
            yield Static(id="station-num")
            with Vertical(classes="station-list"):
                yield Static(id="station-prev", classes="station-prev")
                yield Static(id="station-current", classes="station-current")
                yield Static(id="station-next", classes="station-next")
            yield Static("[dim]───────── NOW PLAYING ─────────[/dim]")
            yield Static(id="preview-artist")
            yield Static(id="preview-song")
            yield Static("[green]ENTER: [OK][/green]  [red]F2/ESC: [CLOSE][/red]", classes="footer")

    def on_mount(self) -> None:
        self._mounted = True
        self._update_display()

    def watch_selected_index(self) -> None:
        if self._mounted:
            self._update_display()

    def _update_display(self) -> None:
        """Update the station selector display."""
        if not self._station_list:
            return

        # Station number
        self.query_one("#station-num", Static).update(
            f"Station {self.selected_index + 1}:"
        )

        # Previous station
        prev_widget = self.query_one("#station-prev", Static)
        if self.selected_index > 0:
            prev_widget.update(f"  {self._station_list[self.selected_index - 1].center(15)}  ")
        else:
            prev_widget.update("")

        # Current station
        current = self._station_list[self.selected_index]
        self.query_one("#station-current", Static).update(
            f"→ {current.center(15)} ←"
        )

        # Next station
        next_widget = self.query_one("#station-next", Static)
        if self.selected_index < len(self._station_list) - 1:
            next_widget.update(f"  {self._station_list[self.selected_index + 1].center(15)}  ")
        else:
            next_widget.update("")

        # Preview metadata
        if self.get_metadata:
            metadata = self.get_metadata(current)
            artist = metadata.artist[:35] + "..." if len(metadata.artist) > 35 else metadata.artist
            song = metadata.song[:35] + "..." if len(metadata.song) > 35 else metadata.song
            self.query_one("#preview-artist", Static).update(
                f"Artist: [cyan]{artist or '---'}[/cyan]"
            )
            self.query_one("#preview-song", Static).update(
                f"  Song: [magenta]{song or '---'}[/magenta]"
            )

    def action_move_up(self) -> None:
        if self.selected_index > 0:
            self.selected_index -= 1

    def action_move_down(self) -> None:
        if self.selected_index < len(self._station_list) - 1:
            self.selected_index += 1

    def action_select(self) -> None:
        self.dismiss(self._station_list[self.selected_index])

    def action_cancel(self) -> None:
        self.dismiss(None)
