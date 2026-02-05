"""Custom Textual widgets for the Nightride FM TUI."""

import random
from textual.reactive import reactive
from textual.widgets import Static


class RadioDisplay(Static):
    """
    Complete radio display with box-drawing frame containing all UI elements.

    Layout (49 chars wide):
    ┏━ ───────── ── ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
    ┃  NIGHTRIDE. FM                               ┃
    ┃  station 1: nightride    VOL: ◄──4───────►   ┃
    ┃  ...............................................┃
    ┃  Artist: Artist Name Here                    ┃
    ┃    Song: Song Title Here                     ┃
    ┃  Played: 00:00                    ▁▂▃▄▅▆▇█   ┃
    ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
    """

    # Reactive properties
    station_num: reactive[str] = reactive("1")
    station_name: reactive[str] = reactive("nightride")
    volume: reactive[int] = reactive(4)
    artist: reactive[str] = reactive("")
    song: reactive[str] = reactive("")
    elapsed: reactive[int] = reactive(0)
    vu_enabled: reactive[bool] = reactive(True)

    # Constants
    FRAME_WIDTH = 49
    CONTENT_WIDTH = 45  # Inside the frame borders
    MAX_TEXT_LEN = 29
    VU_ICONS = "▁▂▃▄▅▆▇█"
    VU_WIDTH = 10

    def _truncate(self, text: str, max_len: int = None) -> str:
        """Truncate text with ellipsis."""
        max_len = max_len or self.MAX_TEXT_LEN
        if len(text) > max_len:
            return text[:max_len - 3] + "..."
        return text

    def _make_volume_slider(self) -> str:
        """Create volume slider string."""
        slider = list("VOL: ◄──────────►")
        slider[self.volume + 6] = str(self.volume)
        return "".join(slider)

    def _make_vu_meter(self) -> str:
        """Create VU meter string."""
        if not self.vu_enabled:
            return " " * self.VU_WIDTH
        return "".join(random.choice(self.VU_ICONS) for _ in range(self.VU_WIDTH))

    def _make_playtime(self) -> str:
        """Create playtime string."""
        minutes = self.elapsed // 60
        seconds = self.elapsed % 60
        return f"Played: {minutes:02d}:{seconds:02d}"

    def _pad_line(self, content: str, width: int = None) -> str:
        """Pad a line to fit inside the frame."""
        width = width or self.CONTENT_WIDTH
        # Account for markup when padding
        visible_len = len(content.replace("[cyan]", "").replace("[/cyan]", "")
                                 .replace("[magenta]", "").replace("[/magenta]", ""))
        padding = width - visible_len
        return content + " " * max(0, padding)

    def render(self) -> str:
        # Build each line (frame is 49 chars wide, content is 45 chars between ┃ borders)
        station_vol = f"station {self.station_num}: {self.station_name}"
        vol_slider = self._make_volume_slider()
        # Pad station info to push volume slider to the right (total 45 chars)
        station_line = (station_vol.ljust(28) + vol_slider).ljust(45)

        artist_display = self._truncate(self.artist) if self.artist else "---"
        song_display = self._truncate(self.song) if self.song else "---"

        playtime = self._make_playtime()
        vu_meter = self._make_vu_meter()
        # Align playtime left, VU meter right (total 45 chars)
        bottom_line = playtime.ljust(35) + vu_meter

        lines = [
            "┏━ [cyan]NIGHTRIDE.[/cyan] [cyan]FM[/cyan] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓",
            f"┃  {station_line}┃",
            "┃  .............................................┃",
            f"┃  Artist: [cyan]{artist_display.ljust(37)}[/cyan]┃",
            f"┃    Song: [magenta]{song_display.ljust(37)}[/magenta]┃",
            f"┃  {bottom_line}┃",
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
        ]
        return "\n".join(lines)

    def update_station(self, num: str, name: str) -> None:
        """Update station display."""
        self.station_num = num
        self.station_name = name

    def set_volume(self, vol: int) -> None:
        """Set volume (0-9)."""
        self.volume = max(0, min(9, vol))

    def update_metadata(self, artist: str, song: str) -> None:
        """Update now playing metadata."""
        self.artist = artist
        self.song = song

    def set_elapsed(self, seconds: int) -> None:
        """Set elapsed playtime."""
        self.elapsed = max(0, seconds)

    def toggle_vu(self) -> None:
        """Toggle VU meter on/off."""
        self.vu_enabled = not self.vu_enabled


class MenuBar(Static):
    """Menu bar showing available key bindings."""

    def render(self) -> str:
        return "[on white black]F1: ABOUT | F2: STATION | -/+: VOLUME | V: VU | F12: QUIT[/]"
