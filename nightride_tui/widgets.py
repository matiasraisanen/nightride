"""Custom Textual widgets for the Nightride FM TUI."""

import random
from textual.reactive import reactive
from textual.widgets import Static


class RadioDisplay(Static):
    """
    Complete radio display with box-drawing frame containing all UI elements.
    Long artist/song names scroll horizontally.

    Layout (49 chars wide):
    ┏━ NIGHTRIDE FM ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
    ┃  station 1: nightride    VOL: ◄──4───────►   ┃
    ┃  .............................................┃
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
    scroll_offset: reactive[int] = reactive(0)

    # Constants
    FRAME_WIDTH = 49
    CONTENT_WIDTH = 45  # Inside the frame borders
    MAX_TEXT_LEN = 37  # Display width for artist/song
    VU_ICONS = "▁▂▃▄▅▆▇█"
    VU_WIDTH = 10
    SCROLL_PADDING = "   ~~~   "  # Padding between scroll cycles

    def _get_scrolling_text(self, text: str, max_len: int) -> str:
        """Get the visible portion of scrolling text."""
        if not text or len(text) <= max_len:
            return (text or "---").ljust(max_len)

        # Create scrolling text with padding for seamless loop
        full_text = text + self.SCROLL_PADDING + text
        offset = self.scroll_offset % (len(text) + len(self.SCROLL_PADDING))
        visible = full_text[offset:offset + max_len]

        # Ensure we always have max_len characters
        if len(visible) < max_len:
            visible += full_text[:max_len - len(visible)]

        return visible

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

    def render(self) -> str:
        # Build each line (frame is 49 chars wide, content is 45 chars between ┃ borders)
        station_vol = f"station {self.station_num}: {self.station_name}"
        vol_slider = self._make_volume_slider()
        # Pad station info to push volume slider to the right (total 45 chars)
        station_line = (station_vol.ljust(28) + vol_slider).ljust(45)

        # Get scrolling text for artist and song
        artist_display = self._get_scrolling_text(self.artist, self.MAX_TEXT_LEN)
        song_display = self._get_scrolling_text(self.song, self.MAX_TEXT_LEN)

        playtime = self._make_playtime()
        vu_meter = self._make_vu_meter()
        # Align playtime left, VU meter right (total 45 chars)
        bottom_line = playtime.ljust(35) + vu_meter

        lines = [
            "┏━ [cyan]NIGHTRIDE[/cyan] [cyan]FM[/cyan] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓",
            f"┃  {station_line}┃",
            "┃  .............................................┃",
            f"┃  Artist: [cyan]{artist_display}[/cyan]┃",
            f"┃    Song: [magenta]{song_display}[/magenta]┃",
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
        # Reset scroll when metadata changes
        if artist != self.artist or song != self.song:
            self.scroll_offset = 0
        self.artist = artist
        self.song = song

    def set_elapsed(self, seconds: int) -> None:
        """Set elapsed playtime."""
        self.elapsed = max(0, seconds)

    def toggle_vu(self) -> None:
        """Toggle VU meter on/off."""
        self.vu_enabled = not self.vu_enabled

    def advance_scroll(self) -> None:
        """Advance the scroll position for long text."""
        # Only scroll if either artist or song is longer than max
        if (len(self.artist) > self.MAX_TEXT_LEN or
                len(self.song) > self.MAX_TEXT_LEN):
            self.scroll_offset += 1
