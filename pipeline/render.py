"""리빙로그 세로 광고 영상 렌더러 (1080x1920, 30fps).

Pillow로 프레임을 그리고 FFmpeg로 인코딩한다. 외부 영상 서비스를 쓰지 않으므로
워터마크가 없고 렌더링 비용이 0원이다.

장면 종류
  hook    : 상품 사진 + 큰 훅 문구(주황 박스)
  benefit : 2줄 헤드라인 + 상품 사진
  proof   : 별점·리뷰 수 숫자 올라가는 효과 + 사진
  price   : 가격 숫자 올라가는 효과 + 배송 배지 + 사진
  cta     : "프로필 링크에서 N번" + 도메인 + 사진
"""
from __future__ import annotations

import glob
import json
import math
import os
import subprocess
import sys
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1920
FPS = 30
BG = (246, 241, 234)
INK = (31, 26, 23)
SUB = (138, 126, 115)
ACC = (194, 65, 12)
WHITE = (255, 255, 255)
SLIDE = 0.28  # 장면 전환(슬라이드) 시간
POP = 0.38  # 글자 등장 시간
COUNT = 0.9  # 숫자 올라가는 시간
DOMAIN = os.environ.get("SITE_DOMAIN", "livinglog7.com")


# ---------------------------------------------------------------- fonts
FONT_CANDIDATES = {
    "black": [
        "fonts/Pretendard-Black.otf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
    ],
    "bold": [
        "fonts/Pretendard-Bold.otf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    ],
    "regular": [
        "fonts/Pretendard-Medium.otf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ],
}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolve(path: str) -> str | None:
    p = path if os.path.isabs(path) else os.path.join(ROOT, path)
    return p if os.path.exists(p) else None


@lru_cache(maxsize=None)
def _font_file(weight: str) -> tuple[str, int]:
    for cand in FONT_CANDIDATES[weight]:
        p = _resolve(cand)
        if not p:
            continue
        if p.endswith(".ttc"):
            for idx in range(10):
                try:
                    f = ImageFont.truetype(p, 20, index=idx)
                except OSError:
                    break
                if "KR" in " ".join(f.getname()):
                    return p, idx
            return p, 0
        return p, 0
    found = glob.glob("/usr/share/fonts/**/*CJK*", recursive=True)
    if found:
        return found[0], 0
    raise RuntimeError("한글 폰트를 찾지 못했습니다")


@lru_cache(maxsize=None)
def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    path, idx = _font_file(weight)
    return ImageFont.truetype(path, size, index=idx)


# ---------------------------------------------------------------- easing
def ease_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def ease_out_back(t: float) -> float:
    t = max(0.0, min(1.0, t))
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


# ---------------------------------------------------------------- drawing helpers
def text_layer(text: str, weight: str, size: int, color, max_width: int = W - 120,
               box=None, pad=(36, 18), radius: int = 22) -> Image.Image:
    """글자 한 줄을 투명 레이어로 그린다. 폭을 넘으면 글자 크기를 줄인다."""
    f = font(weight, size)
    while True:
        bbox = f.getbbox(text)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        limit = max_width - (2 * pad[0] if box else 0)
        if tw <= limit or size <= 30:
            break
        size = int(size * 0.94)
        f = font(weight, size)
    asc, desc = f.getmetrics()
    th = asc + desc
    if box:
        lw, lh = tw + 2 * pad[0], th + 2 * pad[1]
        img = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((0, 0, lw - 1, lh - 1), radius=radius, fill=box)
        d.text((pad[0] - bbox[0], pad[1]), text, font=f, fill=color)
    else:
        img = Image.new("RGBA", (tw + 8, th + 8), (0, 0, 0, 0))
        ImageDraw.Draw(img).text((4 - bbox[0], 4), text, font=f, fill=color)
    return img


def card(path: str, width: int, max_height: int) -> Image.Image:
    """상품 사진을 둥근 모서리 + 그림자 카드로 만든다(확대·흔들림 없음)."""
    src = Image.open(path).convert("RGB")
    scale = min(width / src.width, max_height / src.height)
    w, h = int(src.width * scale), int(src.height * scale)
    src = src.resize((w, h), Image.LANCZOS)
    r = 34
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=255)
    sh = 28
    out = Image.new("RGBA", (w + sh * 2, h + sh * 2), (0, 0, 0, 0))
    shadow = Image.new("RGBA", out.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((sh, sh + 10, sh + w, sh + h + 10), radius=r,
                                             fill=(60, 40, 20, 70))
    out = Image.alpha_composite(out, shadow.filter(ImageFilter.GaussianBlur(16)))
    tile = Image.new("RGBA", (w, h), WHITE + (255,))
    tile.paste(src, (0, 0))
    out.paste(tile, (sh, sh), mask)
    return out


def paste_center(base: Image.Image, layer: Image.Image, cx: int, y: int,
                 scale: float = 1.0, alpha: float = 1.0) -> None:
    if alpha <= 0.01:
        return
    lay = layer
    if abs(scale - 1.0) > 0.005:
        lay = layer.resize((max(1, int(layer.width * scale)), max(1, int(layer.height * scale))),
                           Image.BILINEAR)
    if alpha < 0.999:
        a = lay.getchannel("A").point(lambda v: int(v * alpha))
        lay = lay.copy()
        lay.putalpha(a)
    x = int(cx - lay.width / 2)
    yy = int(y + (layer.height - lay.height) / 2)
    _safe_composite(base, lay, x, yy)


def _safe_composite(base, lay, x, y):
    # 화면 밖으로 일부 나가는 경우(슬라이드 중) 잘라서 합성
    left, top = max(0, x), max(0, y)
    right, bottom = min(base.width, x + lay.width), min(base.height, y + lay.height)
    if right <= left or bottom <= top:
        return
    crop = lay.crop((left - x, top - y, right - x, bottom - y))
    base.alpha_composite(crop, (left, top))


# ---------------------------------------------------------------- scene model
class Pop:
    """등장 애니메이션이 있는 요소"""

    def __init__(self, layer, y, delay=0.0, cx=W // 2, back=True):
        self.layer, self.y, self.delay, self.cx, self.back = layer, y, delay, cx, back

    def draw(self, base, t):
        p = (t - self.delay) / POP
        if p <= 0:
            return
        e = ease_out_back(p) if self.back else ease_out_cubic(p)
        scale = 0.78 + 0.22 * e
        alpha = min(1.0, max(0.0, p * 1.6))
        paste_center(base, self.layer, self.cx, self.y, scale=min(scale, 1.06), alpha=alpha)

    def done(self, t):
        return t >= self.delay + POP


class Counter:
    """숫자가 0에서 목표값까지 올라가는 요소"""

    def __init__(self, value: float, fmt, weight, size, color, y, delay=0.0, decimals=0):
        self.value, self.fmt, self.weight, self.size = value, fmt, weight, size
        self.color, self.y, self.delay, self.decimals = color, y, delay, decimals
        self._final = text_layer(fmt(value), weight, size, color)

    def draw(self, base, t):
        p = (t - self.delay) / COUNT
        if p <= 0:
            return
        if p >= 1:
            paste_center(base, self._final, W // 2, self.y)
            return
        v = self.value * ease_out_cubic(p)
        v = round(v, self.decimals) if self.decimals else int(v)
        lay = text_layer(self.fmt(v), self.weight, self.size, self.color)
        paste_center(base, lay, W // 2, self.y, alpha=min(1.0, p * 3))

    def done(self, t):
        return t >= self.delay + COUNT


def won(n) -> str:
    return f"{int(n):,}원"


def build_scene(sc: dict, no: int) -> tuple[Image.Image, list]:
    """정적 배경 레이어와 애니메이션 요소 목록을 만든다."""
    base = Image.new("RGBA", (W, H), BG + (255,))
    items: list = []
    kind = sc["type"]
    img = sc.get("image")

    if kind == "hook":
        c = card(img, 980, 1080)
        base.alpha_composite(c, ((W - c.width) // 2, 230))
        y = 1330
        for i, line in enumerate(sc["lines"][:2]):
            lay = text_layer(line, "black", 118, WHITE, box=ACC + (255,), pad=(40, 16))
            items.append(Pop(lay, y + i * 200, delay=0.05 + i * 0.18))
    elif kind == "benefit":
        y = 190
        for i, line in enumerate(sc["lines"][:2]):
            items.append(Pop(text_layer(line, "black", 96, INK), y + i * 140, delay=0.05 + i * 0.14))
        c = card(img, 980, 1180)
        base.alpha_composite(c, ((W - c.width) // 2, 520))
    elif kind == "proof":
        items.append(Counter(sc["rating"], lambda v: f"★ {v:.1f}", "black", 210, ACC, 250,
                             delay=0.05, decimals=1))
        items.append(Counter(sc["reviews"], lambda v: f"리뷰 {int(v):,}개", "black", 112, INK, 560,
                             delay=0.25))
        items.append(Pop(text_layer("쿠팡 상품페이지 기준", "regular", 40, SUB), 740, delay=0.6,
                         back=False))
        c = card(img, 900, 900)
        base.alpha_composite(c, ((W - c.width) // 2, 860))
    elif kind == "price":
        y = 200
        if sc.get("label"):
            items.append(Pop(text_layer(sc["label"], "bold", 84, INK), y, delay=0.0))
            y += 150
        items.append(Counter(sc["price"], won, "black", 210, ACC, y, delay=0.1))
        badges = [b for b in sc.get("badges", []) if b][:2]
        if badges:
            lays = [text_layer(b, "bold", 52, WHITE, box=INK + (255,), pad=(30, 12)) for b in badges]
            gap = 24
            total = sum(l.width for l in lays) + gap * (len(lays) - 1)
            x = (W - total) // 2
            for l in lays:
                items.append(Pop(l, y + 300, delay=0.7, cx=x + l.width // 2))
                x += l.width + gap
        items.append(Pop(text_layer("가격은 변동될 수 있어요", "regular", 36, SUB), y + 420,
                         delay=0.9, back=False))
        c = card(img, 900, 860)
        base.alpha_composite(c, ((W - c.width) // 2, 980))
    elif kind == "cta":
        items.append(Pop(text_layer("프로필 링크에서", "black", 92, INK), 210, delay=0.0))
        num = text_layer(f"{no}번", "black", 250, WHITE, box=ACC + (255,), pad=(70, 20), radius=40)
        items.append(Pop(num, 380, delay=0.18))
        items.append(Pop(text_layer(DOMAIN, "bold", 64, INK), 770, delay=0.45, back=False))
        c = card(img, 860, 820)
        base.alpha_composite(c, ((W - c.width) // 2, 940))
    else:
        raise ValueError(f"알 수 없는 장면: {kind}")

    # 모든 장면 공통: 오른쪽 위 "광고 · No.N" 작은 배지
    tag = text_layer(f"광고 · No.{no}", "bold", 34, WHITE, box=(31, 26, 23, 200), pad=(22, 10),
                     radius=18)
    base.alpha_composite(tag, (W - tag.width - 40, 60))
    return base, items


# ---------------------------------------------------------------- audio
def probe_duration(path: str) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", path], capture_output=True, text=True,
                         check=True).stdout.strip()
    return float(out)


def build_audio(scenes: list, durations: list, out: str, bgm: str | None) -> None:
    inputs, filters, labels = [], [], []
    for i, sc in enumerate(scenes):
        inputs += ["-i", sc["audio"]]
        filters.append(f"[{i}:a]aresample=44100,aformat=channel_layouts=stereo,"
                       f"apad=whole_dur={durations[i]:.3f},atrim=0:{durations[i]:.3f}[a{i}]")
        labels.append(f"[a{i}]")
    total = sum(durations)
    filters.append("".join(labels) + f"concat=n={len(scenes)}:v=0:a=1[voice]")
    final = "[voice]"
    if bgm and os.path.exists(bgm):
        inputs += ["-stream_loop", "-1", "-i", bgm]
        b = len(scenes)
        filters.append(f"[{b}:a]aresample=44100,aformat=channel_layouts=stereo,volume=0.13,"
                       f"atrim=0:{total:.3f},afade=t=out:st={max(0, total - 1.2):.3f}:d=1.2[bg]")
        filters.append("[voice][bg]amix=inputs=2:duration=first:dropout_transition=0[mix]")
        final = "[mix]"
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(filters),
                    "-map", final, "-c:a", "aac", "-b:a", "192k", out], check=True)


# ---------------------------------------------------------------- main render
def render(spec: dict, out_path: str, workdir: str) -> dict:
    no = spec["no"]
    scenes = spec["scenes"]
    durations = []
    for sc in scenes:
        d = probe_duration(sc["audio"]) + 0.35 if sc.get("audio") else 3.0
        durations.append(max(d, sc.get("min_duration", 2.2)))

    audio_path = os.path.join(workdir, "audio.m4a")
    build_audio(scenes, durations, audio_path, spec.get("bgm"))

    built = [build_scene(sc, no) for sc in scenes]
    total_frames = int(round(sum(durations) * FPS))
    starts = [0.0]
    for d in durations[:-1]:
        starts.append(starts[-1] + d)

    video_tmp = os.path.join(workdir, "video.mp4")
    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "-", "-i", audio_path, "-c:v", "libx264", "-preset", "medium",
         "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "copy", "-shortest", "-movflags",
         "+faststart", video_tmp], stdin=subprocess.PIPE)

    still_cache: dict[int, bytes] = {}

    def scene_frame(i: int, t: float) -> Image.Image | bytes:
        base, items = built[i]
        if all(it.done(t) for it in items) and i in still_cache:
            return still_cache[i]
        fr = base.copy()
        for it in items:
            it.draw(fr, t)
        if all(it.done(t) for it in items):
            still_cache[i] = fr
        return fr

    for f in range(total_frames):
        t = f / FPS
        i = max(k for k, s in enumerate(starts) if s <= t + 1e-6)
        lt = t - starts[i]
        if i > 0 and lt < SLIDE:
            p = ease_out_cubic(lt / SLIDE)
            prev = scene_frame(i - 1, durations[i - 1])
            cur = scene_frame(i, lt)
            fr = Image.new("RGBA", (W, H), BG + (255,))
            off = int(W * p)
            if off < W:
                fr.alpha_composite(prev.crop((off, 0, W, H)), (0, 0))
            if off > 0:
                fr.alpha_composite(cur.crop((0, 0, off, H)), (W - off, 0))
        else:
            fr = scene_frame(i, lt)
        enc.stdin.write(fr.convert("RGB").tobytes())
    enc.stdin.close()
    if enc.wait() != 0:
        raise RuntimeError("영상 인코딩 실패")
    os.replace(video_tmp, out_path)

    # 썸네일(첫 장면 완성본)
    thumb = os.path.splitext(out_path)[0] + ".jpg"
    scene_frame(0, 5.0).convert("RGB").save(thumb, quality=90)
    return {"duration": round(sum(durations), 2), "thumbnail": thumb, "frames": total_frames}


if __name__ == "__main__":
    spec_path, out = sys.argv[1], sys.argv[2]
    with open(spec_path, encoding="utf-8") as fp:
        sp = json.load(fp)
    wd = os.path.dirname(os.path.abspath(out))
    print(json.dumps(render(sp, out, wd), ensure_ascii=False))
