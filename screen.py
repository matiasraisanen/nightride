import sys
import unicodedata

# Marks that no style has been set yet in a run of output
UNSET = object()


def char_width(c):
    # Japanese and other wide characters take two terminal columns, combining marks none
    if unicodedata.combining(c):
        return 0
    return 2 if unicodedata.east_asian_width(c) in ("W", "F") else 1


def text_width(text):
    return sum(char_width(c) for c in text)


def clip(text, width):
    # The longest start of text that fits in width columns
    used = 0
    for i, c in enumerate(text):
        used += char_width(c)
        if used > width:
            return text[:i]
    return text


class Screen:
    # An off-screen copy of the terminal. Each frame is drawn into it from scratch, and then only the
    # cells that changed since the previous frame are sent to the terminal. That keeps redrawing
    # many times a second cheap and flicker-free.
    #
    # Each cell is (text, style name). A wide character fills its first cell, and its second cell
    # holds "" so it isn't drawn over.

    def __init__(self, term):
        self.term = term
        self.width = 0
        self.height = 0
        self.cells = []
        # What the terminal shows now, or None when it has to be redrawn completely
        self.shown = None
        # Style name => escape sequence that sets its colours
        self.styles = {}

    def invalidate(self):
        # Redraw everything on the next frame, e.g. after the colours of the styles have changed
        self.shown = None

    def begin(self):
        # Start a new frame, following the terminal's current size
        width, height = self.term.width, self.term.height
        if (width, height) != (self.width, self.height):
            self.width, self.height = width, height
            self.shown = None
        self.cells = [[(" ", None)] * width for _ in range(height)]

    def put(self, y, x, text, style):
        if y < 0 or y >= self.height:
            return
        row = self.cells[y]
        for c in text:
            w = char_width(c)
            if w == 0:
                # A combining mark goes on top of the previous character
                if 0 < x <= self.width:
                    previous, previous_style = row[x - 1]
                    row[x - 1] = (previous + c, previous_style)
                continue
            if x < 0:
                x += w
                continue
            if x + w > self.width:
                break
            # Don't leave half of a wide character behind
            if row[x][0] == "":
                row[x - 1] = (" ", row[x - 1][1])
            if x + w < self.width and row[x + w][0] == "":
                row[x + w] = (" ", row[x + w][1])
            row[x] = (c, style)
            if w == 2:
                row[x + 1] = ("", style)
            x += w

    def render(self):
        # Send what changed since the last frame to the terminal
        term = self.term
        out = []
        for y, row in enumerate(self.cells):
            old = self.shown[y] if self.shown is not None else None
            x = 0
            while x < self.width:
                if old is not None and row[x] == old[x]:
                    x += 1
                    continue
                # Draw a run of changed cells
                out.append(term.move_xy(x, y))
                current = UNSET
                while x < self.width and (old is None or row[x] != old[x]):
                    text, style = row[x]
                    if text:
                        if style != current:
                            out.append(term.normal + self.styles.get(style, ""))
                            current = style
                        out.append(text)
                    x += 1
        if out:
            out.append(term.normal)
            sys.stdout.write("".join(out))
            sys.stdout.flush()
        self.shown = self.cells
