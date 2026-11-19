"""Generate resources/icon.ico and icon.png: 16x16 pixel art, scaled without blur."""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "resources"
BG = (30, 30, 40, 255)
NOTE = (54, 210, 122, 255)
SIZES = (16, 24, 32, 48, 64, 128, 256)


def pixel_art() -> Image.Image:
    img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, 15, 15), radius=3, fill=BG)
    d.rectangle((6, 2, 12, 3), fill=NOTE)    # beam
    d.rectangle((6, 2, 6, 10), fill=NOTE)    # left stem
    d.rectangle((12, 2, 12, 9), fill=NOTE)   # right stem
    d.ellipse((2, 9, 6, 12), fill=NOTE)      # left head
    d.ellipse((8, 8, 12, 11), fill=NOTE)     # right head
    return img


def main() -> None:
    OUT.mkdir(exist_ok=True)
    base = pixel_art()
    scaled = [base.resize((s, s), Image.Resampling.NEAREST) for s in SIZES]
    scaled[-1].save(OUT / "icon.png")
    scaled[-1].save(OUT / "icon.ico", sizes=[(s, s) for s in SIZES], append_images=scaled[:-1])
    print("written", OUT / "icon.ico")


if __name__ == "__main__":
    main()
