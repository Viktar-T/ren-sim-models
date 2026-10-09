"""Read the Sandia 17-m field test points off Figure 6 of NASA NTRS 19800008205 (spec 0004).

Run by hand, with network: `uv run python make_sandia_17m.py`. Needs poppler's `pdftoppm`,
Pillow and SciPy. Must not import kiozesim. Writes measured.csv next to this file.

Method: render page 10 at 300 dpi; calibrate the axes from the frame and tick marks found in the
image; find the circle markers by matching a ring the size of the legend's circle (radius 13.5 px)
and keep local maxima scoring at least 0.8 of the legend circle (lower scores are the curve
crossing a circle; checked by eye on an overlay, 30 circles).
"""

import subprocess
import tempfile
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage, signal

URL = "https://ntrs.nasa.gov/api/citations/19800008205/downloads/19800008205.pdf"
HERE = Path(__file__).parent
# Pixel positions at 300 dpi, found in the image: frame edges and tick marks.
X_PX, X_VAL = [739.0, 1285.0, 1466.5, 1646.0, 1824.5], [0, 6, 8, 10, 12]
Y_PX, Y_VAL = [2702.0, 2520.5, 2336.5, 2154.5], [0.10, 0.20, 0.30, 0.40]
LEGEND = (2755, 802)  # centre of the legend's circle (row, column)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "ntrs.pdf"
        urllib.request.urlretrieve(URL, pdf)
        subprocess.run(["pdftoppm", "-r", "300", "-gray", "-f", "10", "-l", "10", pdf, f"{tmp}/p"])
        image = np.array(Image.open(next(Path(tmp).glob("p-*.pgm")))).astype(float)
    dark = (image < 128).astype(float)
    yy, xx = np.mgrid[-18:19, -18:19]
    rr = np.hypot(yy, xx)
    ring = np.where((rr >= 11.5) & (rr <= 15.5), 1.0, 0.0) - np.where(rr < 9, 0.6, 0.0)
    score = signal.fftconvolve(dark, ring[::-1, ::-1], mode="same")
    local_max = score == ndimage.maximum_filter(score, size=15)
    peaks = np.argwhere(local_max & (score >= 0.8 * score[LEGEND]))
    fx, fy = np.polyfit(X_PX, X_VAL, 1), np.polyfit(Y_PX, Y_VAL, 1)
    rows = []
    for y, x in peaks:
        tsr, cp = np.polyval(fx, x), np.polyval(fy, y)
        if 2.0 < tsr < 10.5 and 0.08 < cp < 0.46 and not (y > 2700 and x < 900):  # not the legend
            rows.append((tsr, cp))
    rows.sort()
    lines = ["tsr,cp"] + [f"{t:.3f},{c:.4f}" for t, c in rows]
    (HERE / "measured.csv").write_text("\n".join(lines) + "\n")
    print(f"{len(rows)} points written")


if __name__ == "__main__":
    main()
