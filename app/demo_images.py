"""시연용 현장 사진 (Pillow 절차적 렌더링, 외부 이미지 미사용).

실제 사진이 아닌 '현장 사진 느낌'의 예시 이미지입니다. (참고 아티팩트의 캔버스 장면을 단순화)
"""
import io
import os
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 800, 600
_FONT_PATHS = [
    r"C:\Windows\Fonts\malgunbd.ttf", r"C:\Windows\Fonts\malgun.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf", "/System/Library/Fonts/AppleSDGothicNeo.ttc",
]


def _font(size):
    for p in _FONT_PATHS:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                pass
    return ImageFont.load_default()


def _shed(d, R, hz=250, vp=400):
    for y in range(hz):  # 천장
        c = int(44 + (93 - 44) * y / hz)
        d.line([(0, y), (W, y)], fill=(c, c + 6, c + 12))
    for k in range(7):  # 조명
        t = 1 / (k * 0.9 + 1)
        y = hz - (hz - 30) * t
        w = 220 * t
        for sd in (-1, 1):
            cx = vp + sd * 260 * t
            d.rectangle([cx - w / 2, y, cx + w / 2, y + max(2, 9 * t)], fill=(255, 251, 234))
    d.rectangle([vp - 330, hz - 70, vp + 330, hz], fill=(138, 146, 151))
    for i in range(9):
        d.rectangle([vp - 300 + i * 68, hz - 60, vp - 256 + i * 68, hz - 38], fill=(225, 238, 248))
    for y in range(hz, H):  # 바닥
        c = int(111 + (165 - 111) * (y - hz) / (H - hz))
        d.line([(0, y), (W, y)], fill=(c, c + 3, c + 2))
    for i in range(-6, 7):
        d.line([(vp + i * 50, hz), (vp + i * 420, H)], fill=(80, 80, 80), width=1)
    for _ in range(30):
        x, y = R.random() * W, hz + 10 + R.random() * (H - hz)
        s = 10 + 60 * R.random()
        g = int(90 + R.random() * 80)
        d.ellipse([x, y, x + s, y + s * 0.3], fill=(g, g, g - 5))


def _hazard(d, box, step=20):
    x0, y0, x1, y1 = box
    d.rectangle(box, fill=(232, 185, 15))
    for i in range(int(x0) - int(y1 - y0), int(x1), step * 2):
        d.polygon([(i, y1), (i + step, y1), (i + step + (y1 - y0), y0), (i + (y1 - y0), y0)], fill=(29, 29, 29))
    d.rectangle(box, outline=(29, 29, 29))


def _scene(d, key, kind, R):
    before = kind == "before"
    if key == "oil":
        _shed(d, R)
        d.rectangle([560, 330, 680, 425], fill=(217, 165, 11))
        _hazard(d, (560, 405, 680, 419), 10)
        d.line([(565, 360), (480, 380), (470, 470), (380, 480)], fill=(17, 17, 17), width=9)
        if before:
            for (cx, cy, rx, ry) in ((420, 500, 150, 40), (350, 508, 70, 22), (495, 490, 80, 24)):
                d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=(28, 22, 12))
            d.ellipse([400, 486, 470, 496], fill=(120, 90, 150))
        else:
            d.polygon([(330, 478), (440, 478), (452, 500), (318, 500)], fill=(142, 150, 156))
            d.rectangle([371, 470, 389, 475], fill=(46, 125, 50))
    elif key == "pit":
        _shed(d, R, hz=230)
        d.polygon([(394, 230), (406, 230), (596, H), (204, H)], fill=(27, 29, 31))
        _hazard(d, (190, 560, 610, 580), 18)
        posts = [(150, 330), (190, 380), (230, 430), (270, 480), (310, 530)]
        missing = {1, 2} if before else set()
        for i, (x, y) in enumerate(posts):
            if i in missing:
                continue
            d.line([(x, y), (x, y - 140)], fill=(226, 177, 12), width=10)
            if i + 1 < len(posts) and i + 1 not in missing:
                nx, ny = posts[i + 1]
                d.line([(x, y - 140), (nx, ny - 140)], fill=(226, 177, 12), width=7)
                d.line([(x, y - 70), (nx, ny - 70)], fill=(226, 177, 12), width=7)
        if before:
            d.polygon([(90, 560), (320, 530), (322, 542), (92, 572)], fill=(199, 155, 11))
        else:
            d.polygon([(300, 470), (500, 470), (560, H), (240, H)], fill=(160, 166, 170))
    elif key == "loto":
        d.rectangle([0, 0, W, H], fill=(130, 136, 141))
        d.rectangle([90, 40, 710, 560], fill=(215, 217, 214), outline=(155, 158, 154), width=6)
        d.rectangle([130, 62, 470, 96], fill=(31, 61, 107))
        d.text((142, 66), "분전반 P-2 (검수고 2번선)", font=_font(20), fill="white")
        for r in range(3):
            y = 150 + r * 135
            d.rectangle([120, y + 40, 680, y + 54], fill=(167, 170, 166))
            for i in range(9):
                bx = 135 + i * 60
                main = r == 0 and i < 2
                d.rectangle([bx, y, bx + 50, y + 98], fill=(43, 43, 43) if main else (239, 239, 234))
                d.rectangle([bx + 17, y + 34, bx + 33, y + 54], fill=(198, 40, 40) if main else (51, 51, 51))
        if not before:
            d.rectangle([140, 182, 238, 208], fill=(211, 47, 47))
            d.rounded_rectangle([162, 248, 218, 306], 8, fill=(200, 30, 30))
            d.rectangle([145, 340, 265, 510], fill="white", outline=(198, 40, 40), width=3)
            d.rectangle([145, 340, 265, 384], fill=(198, 40, 40))
            d.text((175, 346), "위 험", font=_font(26), fill="white")
            d.text((160, 400), "조작금지", font=_font(20), fill=(17, 17, 17))
            d.text((165, 440), "LOCK OUT", font=_font(16), fill=(17, 17, 17))
        else:
            d.line([(240, 600), (250, 520), (220, 470), (260, 430)], fill=(51, 51, 51), width=3)
    elif key == "rope":
        d.rectangle([0, 0, W, H], fill=(55, 61, 68))
        d.rectangle([0, 40, W, 90], fill=(170, 140, 40))
        base = (110, 100, 88) if before else (170, 176, 181)
        for i in range(-20, 60):
            x = i * 15
            d.line([(x, 640), (x + 520, 0)], fill=base, width=12)
            d.line([(x + 6, 640), (x + 526, 0)], fill=(40, 40, 40), width=2)
        if before:
            for _ in range(26):
                x, y = 250 + R.random() * 300, 150 + R.random() * 300
                d.ellipse([x, y, x + 20, y + 10], fill=(160, 85, 30))
            for _ in range(16):
                x, y = 420 + R.random() * 60, 260 + R.random() * 60
                d.line([(x, y), (x + R.uniform(-40, 40), y + R.uniform(-50, 50))], fill=(184, 176, 162), width=2)
        else:
            d.rounded_rectangle([600, 30, 750, 140], 12, fill=(227, 177, 12))
            d.rectangle([612, 78, 738, 104], fill=(46, 125, 50))
            d.text((620, 80), "점검필·로프교체", font=_font(15), fill="white")
    elif key == "ext":
        d.rectangle([0, 0, W, H], fill=(195, 188, 172))
        d.rounded_rectangle([330, 205, 690, 640], 60, fill=(200, 40, 34))
        d.rectangle([380, 360, 640, 530], fill="white")
        d.rectangle([380, 360, 640, 402], fill=(198, 40, 40))
        d.text((400, 368), "분말소화기 3.3kg", font=_font(24), fill="white")
        d.ellipse([180, 80, 420, 320], fill=(170, 170, 170))
        d.ellipse([194, 94, 406, 306], fill=(251, 251, 248))
        d.arc([216, 116, 384, 284], 144, 205, fill=(211, 47, 47), width=18)
        d.arc([216, 116, 384, 284], 205, 304, fill=(46, 158, 91), width=18)
        d.arc([216, 116, 384, 284], 304, 396, fill=(211, 47, 47), width=18)
        import math
        a = math.radians(160 if before else 255)
        d.line([(300, 200), (300 + math.cos(a) * 95, 200 + math.sin(a) * 95)], fill=(17, 17, 17), width=6)
        d.ellipse([289, 189, 311, 211], fill=(17, 17, 17))
        d.text((276, 240), "MPa", font=_font(18), fill=(34, 34, 34))
        if not before:
            d.rectangle([90, 330, 240, 540], fill="white")
            d.rectangle([90, 330, 240, 364], fill=(31, 61, 107))
            d.text((105, 336), "소화기 점검표", font=_font(16), fill="white")
            for i in range(5):
                d.text((200, 372 + i * 30), "✓", font=_font(20), fill=(46, 125, 50))
    elif key == "helmet":
        _shed(d, R, hz=330, vp=260)
        d.pieslice([250, 440, 730, 760], 180, 360, fill=(36, 52, 79))
        d.ellipse([400, 200, 600, 410], fill=(214, 166, 128))
        d.chord([360, 120, 640, 330], 180, 360, fill=(236, 238, 240))
        d.rectangle([350, 262, 690, 286], fill=(220, 222, 224))
        d.text((395, 205), "안전제일", font=_font(18), fill=(31, 61, 107))
        if before:
            d.line([(445, 285), (430, 380), (440, 470)], fill=(34, 34, 34), width=9)
        else:
            d.line([(450, 285), (500, 390), (548, 404)], fill=(34, 34, 34), width=9)
            d.line([(565, 285), (575, 360), (556, 402)], fill=(34, 34, 34), width=9)
            d.rectangle([540, 394, 562, 412], fill=(17, 17, 17))
    elif key == "chock":
        d.rectangle([0, 0, W, H], fill=(62, 68, 73))
        d.rectangle([0, 470, W, H], fill=(107, 109, 106))
        d.rectangle([0, 455, W, 475], fill=(158, 162, 165))
        d.ellipse([180, 60, 580, 460], fill=(50, 54, 58))
        d.ellipse([310, 190, 450, 330], fill=(62, 67, 71))
        d.polygon([(560, 455), (700, 455), (700, 395)], fill=(198, 40, 40))
        d.text((610, 425), "수용쐐기", font=_font(15), fill="white")
    elif key == "weld":
        _shed(d, R, vp=380)
        for i in range(3):
            x = 120 + i * 190
            d.rectangle([x, 180, x + 180, 470], fill=(225, 90, 35))
            d.rectangle([x, 172, x + 180, 182], fill=(85, 85, 85))
        d.rectangle([80, 470, 720, 510], fill=(122, 122, 114))
        d.rounded_rectangle([720, 360, 770, 490], 12, fill=(198, 40, 40))
    else:  # aisle
        _shed(d, R, hz=260, vp=420)
        for sd in (-1, 1):
            d.polygon([(420 + sd * 30, 260), (420 + sd * 34, 260), (420 + sd * 260, H), (420 + sd * 230, H)],
                      fill=(232, 194, 26))
        d.polygon([(412, 300), (428, 300), (460, 420), (380, 420)], fill=(46, 125, 50))
        d.rectangle([40, 300, 190, 460], fill=(61, 90, 128))
        d.rectangle([640, 320, 760, 440], fill=(122, 127, 132))


def render(key, kind, when_text, seed_text=""):
    """장면 key + 종류(before/after/normal) → JPEG bytes."""
    R = random.Random(f"{key}|{kind}|{seed_text}")
    img = Image.new("RGB", (W, H), (240, 238, 232))
    d = ImageDraw.Draw(img)
    _scene(d, key, kind, R)
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    # 노이즈 + 비네팅 느낌
    px = img.load()
    for _ in range(9000):
        x, y = R.randrange(W), R.randrange(H)
        r, g, b = px[x, y]
        n = R.randint(-18, 18)
        px[x, y] = (max(0, min(255, r + n)), max(0, min(255, g + n)), max(0, min(255, b + n)))
    d = ImageDraw.Draw(img)
    f = _font(24)
    d.text((W - 262, H - 46), when_text, font=f, fill=(0, 0, 0))
    d.text((W - 264, H - 48), when_text, font=f, fill=(255, 163, 42))
    d.text((14, 12), "시연용 예시 이미지", font=_font(16), fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=82)
    return buf.getvalue()
