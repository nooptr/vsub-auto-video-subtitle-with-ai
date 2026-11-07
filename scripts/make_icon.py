"""Vẽ icon cho Vsub.app (PNG 1024px) — không cần font: ô vuông bo góc + 'khung phim' + 2 dòng phụ đề."""
import sys

from PIL import Image, ImageDraw

S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
# nền: gradient xanh đậm -> xanh dương
top, bot = (30, 41, 99), (37, 99, 235)
grad = Image.new("RGBA", (S, S))
gd = ImageDraw.Draw(grad)
for y in range(S):
    t = y / S
    gd.line([(0, y), (S, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bot)) + (255,))
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([80, 80, S - 80, S - 80], radius=190, fill=255)
img.paste(grad, (0, 0), mask)
# màn hình phim
d.rounded_rectangle([190, 250, S - 190, 700], radius=48, fill=(15, 23, 42, 255))
d.polygon([(470, 380), (470, 560), (610, 470)], fill=(96, 165, 250, 255))  # nút play
# hai dòng phụ đề
d.rounded_rectangle([250, 745, S - 250, 800], radius=28, fill=(255, 255, 255, 255))
d.rounded_rectangle([330, 830, S - 330, 885], radius=28, fill=(250, 204, 21, 255))
out = sys.argv[1] if len(sys.argv) > 1 else "vsub.png"
if out.lower().endswith(".ico"):  # Windows: nhiều cỡ trong một file
    img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
else:
    img.save(out)
