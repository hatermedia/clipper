from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ASSETS = Path(r"C:\Users\ADMIN\clipper\docs\service\assets")
SCREENSHOT = Path(r"C:\Users\ADMIN\clipper\docs\screenshot.png")

W, H = 1600, 1000
bg = Image.new("RGB", (W, H), (6, 9, 15))
draw = ImageDraw.Draw(bg)

bold = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", 40)
h2 = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", 24)
body = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 18)
small = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 15)
mono = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 17)
mono_bold = ImageFont.truetype(r"C:\Windows\Fonts\consolab.ttf", 17)
tiny = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 13)

# Header
draw.text((52, 38), "YOUR DELIVERY", font=bold, fill=(255, 255, 255))
draw.text((52, 92), "10 named clips. A clip list. Preview frames. One revision.", font=body, fill=(148, 163, 184))
draw.rounded_rectangle([1352, 44, 1548, 82], radius=19, fill=(34, 211, 238))
draw.text((1380, 53), "READY TO POST", font=tiny, fill=(4, 16, 24))

# Left file panel
panel = [52, 142, 1052, 842]
draw.rounded_rectangle(panel, radius=16, fill=(11, 17, 27), outline=(31, 45, 64), width=1)
draw.text((76, 162), "clipper_delivery / my-game-session", font=mono_bold, fill=(226, 232, 240))
draw.text((76, 190), "10 clips · 2h footage · 48h turnaround", font=small, fill=(100, 116, 139))

files = []
for index in range(1, 11):
    start = 12 + (index - 1) * 37
    end = start + 6
    files.append(
        (
            f"gameplay_20261123_clip{index:02d}_{start // 60:02d}m{start % 60:02d}s-{end // 60:02d}m{end % 60:02d}s.mp4",
            f"{start // 60}:{start % 60:02d} - {end // 60}:{end % 60:02d}",
            f"{38 + index * 2} MB",
        )
    )

y = 224
for index, (name, timecode, size) in enumerate(files):
    if index % 2 == 0:
        draw.rounded_rectangle([64, y - 6, 1040, y + 38], radius=7, fill=(15, 23, 36))
    # play triangle
    draw.polygon([(82, y + 8), (82, y + 24), (94, y + 16)], fill=(34, 211, 238))
    draw.text((108, y + 1), name, font=mono, fill=(203, 213, 225))
    draw.text((108, y + 19), timecode, font=tiny, fill=(100, 116, 139))
    draw.text((930, y + 7), size, font=mono, fill=(100, 116, 139))
    y += 48

# Bottom supporting files
y += 6
draw.line([64, y, 1040, y], fill=(31, 45, 64), width=1)
y += 14
for icon, name, note in [
    ("CSV", "clips.csv", "id, file, start, end, score"),
    ("JPG", "previews/", "10 preview frames for quick review"),
    ("TXT", "delivery-notes.txt", "what was kept, what was skipped"),
]:
    draw.rounded_rectangle([64, y, 1040, y + 42], radius=7, fill=(9, 15, 24), outline=(24, 36, 52), width=1)
    draw.rounded_rectangle([78, y + 8, 114, y + 34], radius=5, fill=(34, 211, 238, 40), outline=(34, 211, 238), width=1)
    draw.text((84, y + 13), icon, font=tiny, fill=(103, 232, 249))
    draw.text((128, y + 5), name, font=mono_bold, fill=(226, 232, 240))
    draw.text((128, y + 23), note, font=tiny, fill=(100, 116, 139))
    y += 50

# Right preview panel
right = [1080, 142, 1548, 842]
draw.rounded_rectangle(right, radius=16, fill=(11, 17, 27), outline=(31, 45, 64), width=1)
draw.text((1104, 162), "PREVIEW", font=mono_bold, fill=(226, 232, 240))
draw.text((1104, 190), "Every clip has a frame you can scan first.", font=small, fill=(100, 116, 139))

shot = Image.open(SCREENSHOT).convert("RGB")
shot.thumbnail((420, 260), Image.LANCZOS)
bg.paste(shot, (1104, 226))
draw.rectangle([1104, 226, 1104 + shot.width, 226 + shot.height], outline=(42, 58, 82), width=1)
draw.text((1104, 506), "Demo UI · synthetic sample footage", font=tiny, fill=(100, 116, 139))

# Checklist
items = [
    "10 clips, named and timestamped",
    "Lossless or re-encoded MP4",
    "No watermark, no subscription",
    "1 revision round",
    "Footage deleted 7 days after delivery",
]
y2 = 548
for item in items:
    draw.ellipse([1104, y2 + 5, 1118, y2 + 19], fill=(52, 211, 153))
    draw.text((1130, y2), item, font=small, fill=(203, 213, 225))
    y2 += 34

draw.text((1104, 760), "You keep the rights.", font=h2, fill=(255, 255, 255))
draw.text((1104, 792), "The service is optional; the tool stays MIT.", font=small, fill=(100, 116, 139))

# Footer
draw.line([52, 884, 1548, 884], fill=(24, 36, 52), width=1)
draw.text((52, 910), "Pilot pricing: $29 intro for the first five orders, then $49.", font=body, fill=(148, 163, 184))
draw.text((52, 946), "Request a slot through the GitHub issue template. No payment is collected on the website.", font=small, fill=(71, 85, 105))

bg.save(ASSETS / "deliverables.jpg", quality=92)
print("deliverables", (ASSETS / "deliverables.jpg").stat().st_size)
