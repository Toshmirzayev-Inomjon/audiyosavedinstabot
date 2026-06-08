from __future__ import annotations

from pathlib import Path

from PIL import Image


async def make_sticker(source: Path, output: Path) -> Path:
    image = Image.open(source).convert("RGBA")
    image.thumbnail((512, 512))
    canvas = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    x = (512 - image.width) // 2
    y = (512 - image.height) // 2
    canvas.alpha_composite(image, (x, y))
    canvas.save(output, "WEBP")
    return output


async def upscale_image(source: Path, output: Path, factor: int = 2) -> Path:
    image = Image.open(source).convert("RGB")
    resized = image.resize(
        (image.width * factor, image.height * factor),
        Image.Resampling.LANCZOS,
    )
    resized.save(output)
    return output


async def remove_light_background(source: Path, output: Path, threshold: int = 245) -> Path:
    image = Image.open(source).convert("RGBA")
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            red, green, blue, alpha = pixels[x, y]
            if red >= threshold and green >= threshold and blue >= threshold:
                pixels[x, y] = (red, green, blue, 0)
            else:
                pixels[x, y] = (red, green, blue, alpha)
    image.save(output)
    return output
