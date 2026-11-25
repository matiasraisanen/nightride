# Makes windows/nightride.ico from windows/nightride.svg, with each size drawn from the SVG, so the
# small ones stay sharp. Only needed when the icon changes: the .ico is kept in the repository.
#     pip install cairosvg pillow
#     python windows/make_icon.py
import io
import os

import cairosvg
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SIZES = [256, 128, 64, 48, 32, 24, 16]

svg = open(os.path.join(HERE, "nightride.svg"), "rb").read()
images = [
    Image.open(io.BytesIO(cairosvg.svg2png(bytestring=svg, output_width=size, output_height=size))).convert("RGBA")
    for size in SIZES
]
images[0].save(
    os.path.join(HERE, "nightride.ico"), format="ICO", sizes=[(s, s) for s in SIZES], append_images=images[1:]
)
print("Wrote windows/nightride.ico")
