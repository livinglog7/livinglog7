"""리빙로그 하루 1편 자동 제작.

1) 오늘의 키워드로 쿠팡 판매량순 상품 검색 → 별점·리뷰 기준으로 1개 선택
2) 실제 판매 사진 수집
3) Gemini가 사진을 보고 장면별 문구·내레이션 작성 (사실만)
4) ElevenLabs(Anna Kim)로 장면별 음성 생성
5) 영상 렌더링 (워터마크 없음)
6) GitHub 릴리스에 영상 업로드, 상품 사이트·latest.json 갱신

환경변수: APIFY_TOKEN, GEMINI_API_KEY, ELEVENLABS_API_KEY, GITHUB_TOKEN
선택: ELEVENLABS_VOICE_ID, FORCE_KEYWORD, DRY_RUN=1(업로드 없이 영상만)
"""
from __future__ import annotations

import base64
import datetime as dt
import io
import json
import os
import re
import sys
import time

import requests
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402
import render  # noqa: E402
import site_build  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
DB = os.path.join(DOCS, "products.json")
WORK = os.path.join(ROOT, "work")
KST = dt.timezone(dt.timedelta(hours=9))


def log(*a):
    print("[리빙로그]", *a, flush=True)


def env(name: str, required=True) -> str:
    v = os.environ.get(name, "").strip()
    if required and not v:
        raise SystemExit(f"환경변수 {name} 가 비어 있습니다 (GitHub Secrets 확인)")
    return v


def with_retry(fn, tries=3, wait=8, what=""):
    last = None
    for k in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            log(f"{what} 실패 {k + 1}/{tries}: {e}")
            time.sleep(wait * (k + 1))
    raise last


# ---------------------------------------------------------------- 한국어 숫자 읽기
DIG = ["", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구"]


def _under_10000(n: int) -> str:
    out = ""
    for unit, name in ((1000, "천"), (100, "백"), (10, "십"), (1, "")):
        d = n // unit % 10
        if d:
            out += ("" if d == 1 and name else DIG[d]) + name
    return out


def korean_number(n: int) -> str:
    if n == 0:
        return "영"
    parts = []
    for unit, name in ((10 ** 8, "억"), (10 ** 4, "만"), (1, "")):
        q = n // unit % 10000
        if q:
            parts.append(name if (q == 1 and name) else _under_10000(q) + name)
    return " ".join(parts)


def rough_count(n: int) -> str:
    """27674 -> '2만 7천' 처럼 말하기 쉬운 근사치"""
    if n >= 10000:
        man, rest = divmod(n, 10000)
        cheon = rest // 1000
        return f"{korean_number(man)}만" + (f" {DIG[cheon] if cheon > 1 else ''}천" if cheon else "")
    if n >= 1000:
        return f"{korean_number(n // 1000 * 1000)}"
    return korean_number(n)


def rating_words(r: float) -> str:
    a, b = f"{r:.1f}".split(".")
    return f"{DIG[int(a)] or '영'} 점 {DIG[int(b)] or '영'}"


# ---------------------------------------------------------------- 상품 DB
def load_db() -> list:
    if os.path.exists(DB):
        with open(DB, encoding="utf-8") as fp:
            return json.load(fp)
    return []


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------- Apify (쿠팡)
def apify(payload: dict, limit: int) -> list:
    tok = env("APIFY_TOKEN")
    url = f"https://api.apify.com/v2/acts/{config.APIFY_ACTOR}/run-sync-get-dataset-items"
    r = requests.post(url, params={"token": tok, "limit": limit, "maxTotalChargeUsd": "0.1",
                                   "timeout": "280"}, json=payload, timeout=320)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else []


def partner_link(p: dict) -> str:
    q = [f"lptag={config.PARTNER_ID}", f"pageKey={p['productId']}"]
    if p.get("itemId"):
        q.append(f"itemId={p['itemId']}")
    if p.get("vendorItemId"):
        q.append(f"vendorItemId={p['vendorItemId']}")
    return "https://link.coupang.com/re/AFFSDP?" + "&".join(q)


def pick_product(used: set) -> tuple[dict, str]:
    forced = os.environ.get("FORCE_KEYWORD", "").strip()
    day = dt.datetime.now(KST).toordinal()
    order = [forced] if forced else [config.KEYWORDS[(day + k) % len(config.KEYWORDS)]
                                     for k in range(3)]
    for kw in order:
        log("키워드:", kw)
        items = with_retry(lambda: apify({"mode": "search", "queries": [kw],
                                          "sortBy": "saleCountDesc", "minRating": 4,
                                          "maxPages": 1, "maxListings": 20,
                                          "fetchDetails": False}, 20), what="상품 검색")
        items = [x for x in items if x.get("title") and x.get("productId") and not x.get("isAd")]
        fresh = [x for x in items if str(x["productId"]) not in used]
        good = [x for x in fresh if float(x.get("rating") or 0) >= config.MIN_RATING
                and int(x.get("reviewCount") or 0) >= config.MIN_REVIEWS]
        pool = good or fresh
        if not pool:
            log("새 상품 없음, 다음 키워드로")
            continue
        top = sorted(pool[:5], key=lambda x: int(x.get("reviewCount") or 0), reverse=True)[0]
        return top, kw
    raise SystemExit("오늘 키워드들에서 새 상품을 찾지 못했습니다")


def product_detail(listing: dict) -> dict:
    url = listing["url"]
    if not url.startswith("http"):
        url = "https://www.coupang.com" + ("" if url.startswith("/") else "/") + url
    rows = with_retry(lambda: apify({"mode": "url", "urls": [url], "fetchDetails": True,
                                     "maxPages": 1, "maxListings": 1}, 1), what="상세 수집")
    d = rows[0] if rows else {}
    merged = dict(listing)
    merged.update({k: v for k, v in d.items() if v not in (None, "", [])})
    merged["url"] = url
    imgs = []
    for x in (d.get("images") or []) + (listing.get("images") or []) + [listing.get("image")]:
        u = x if isinstance(x, str) else (x or {}).get("url")
        if u and u.startswith("http") and u not in imgs:
            imgs.append(u)
    merged["images"] = imgs
    return merged


def download_images(urls: list, folder: str) -> list:
    os.makedirs(folder, exist_ok=True)
    out = []
    for i, u in enumerate(urls[:12]):
        u2 = re.sub(r"/thumbnails/remote/\d+x\d+ex/", "/thumbnails/remote/1000x1000ex/", u)
        for cand in (u2, u):
            try:
                r = requests.get(cand, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
                r.raise_for_status()
                im = Image.open(io.BytesIO(r.content)).convert("RGB")
                if min(im.size) < 300:
                    break
                p = os.path.join(folder, f"img{len(out)}.jpg")
                im.save(p, quality=92)
                out.append({"path": p, "url": u, "size": im.size})
                break
            except Exception as e:  # noqa: BLE001
                log("사진 받기 실패:", cand[:80], e)
    if len(out) < 3:
        raise SystemExit(f"쓸 수 있는 상품 사진이 {len(out)}장뿐입니다 (최소 3장)")
    return out


# ---------------------------------------------------------------- Gemini 대본
PROMPT = """너는 살림 채널 '리빙로그'의 숏폼 광고 카피라이터다. 첨부한 상품 사진(번호 0부터)과 아래 '확인된 정보'만 보고,
보는 사람이 '이거 사야겠다'고 느끼게 하는 25초 세로 광고 영상의 장면 문구를 만든다.

절대 규칙
- 사진과 확인된 정보에 없는 기능·수치·효능·후기는 지어내지 않는다. 사진에서 분명히 보이는 사용 장면은 써도 된다.
- '최고', '1위', '무조건', '완벽' 같은 최상급·과장, 의학적 효능 표현 금지.
- 말투: 친근한 살림 고수의 존댓말 구어체. 짧고 리듬감 있게.
- 각 화면 문구(lines)는 2줄, 한 줄 9자 이내(공백 포함). 단어가 줄 사이에서 끊기지 않게 나눈다.
- narration은 한 문장 30자 이내, 소리 내어 읽기 자연스럽게. 괄호·이모지·영문·특수기호 금지.

장면 구성
- hook: 시청자가 겪는 생활 속 불편을 찌르는 질문이나 공감(스크롤을 멈추게). 가장 상황이 잘 보이는 사진 선택.
- benefits: 3개. 각각 서로 다른 장점(공간·사용법·보관·다른 용도 등)을 보여주는 서로 다른 사진 선택. 사람이 쓰는 장면 사진을 우선.
- proof_image / price_image / cta_image: 상품 전체가 잘 보이는 사진.
- price_label: 상품명에 구성(예: 3개 세트, 2팩)이 분명히 있을 때만 '3개 세트'처럼, 없으면 빈 문자열.

반드시 아래 JSON만 출력:
{"hook": {"lines": ["", ""], "narration": "", "image": 0},
 "benefits": [{"lines": ["", ""], "narration": "", "image": 1}, ...3개],
 "proof_image": 0, "price_image": 0, "cta_image": 0, "price_label": "",
 "youtube_title": "60자 이내 검색 잘 되는 제목", "hashtags": ["#..", "#..", "#..", "#..", "#.."]}

[확인된 정보]
상품명: {title}
브랜드: {brand}
가격: {price}원
별점: {rating} / 리뷰 수: {reviews}
배송: {delivery}
카테고리: {category}
설명: {desc}
사진 수: {n}
"""


def gemini_script(p: dict, imgs: list) -> dict:
    key = env("GEMINI_API_KEY")
    delivery = ", ".join(x for x in ["로켓배송" if p.get("rocketDelivery") else "",
                                     "무료배송" if p.get("freeShipping") else ""] if x) or "정보 없음"
    text = PROMPT.format(title=p.get("title"), brand=p.get("brand") or "정보 없음",
                         price=p.get("price"), rating=p.get("rating"),
                         reviews=p.get("reviewCount"), delivery=delivery,
                         category=p.get("categoryPath") or "정보 없음",
                         desc=(p.get("description") or "정보 없음")[:600], n=len(imgs))
    parts = [{"text": text}]
    for im in imgs[:10]:
        thumb = Image.open(im["path"])
        thumb.thumbnail((512, 512))
        b = io.BytesIO()
        thumb.save(b, "JPEG", quality=80)
        parts.append({"inline_data": {"mime_type": "image/jpeg",
                                      "data": base64.b64encode(b.getvalue()).decode()}})
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{config.GEMINI_MODEL}:generateContent")

    def call():
        r = requests.post(url, headers={"x-goog-api-key": key}, timeout=120, json={
            "contents": [{"parts": parts}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.8}})
        r.raise_for_status()
        raw = "".join(x.get("text", "") for x in r.json()["candidates"][0]["content"]["parts"])
        return json.loads(raw[raw.index("{"): raw.rindex("}") + 1])

    s = with_retry(call, tries=4, wait=10, what="Gemini 대본")
    n = len(imgs)

    def idx(v, default):
        try:
            v = int(v)
        except (TypeError, ValueError):
            return default
        return v if 0 <= v < n else default

    def clean(t, limit):
        t = re.sub(r"[\(\)\[\]{}<>*#\"“”]", "", str(t or "")).strip()
        return t[:limit]

    def lines(v):
        ls = [clean(x, 11) for x in (v or []) if clean(x, 11)]
        return ls[:2] or ["", ""]

    hook = s.get("hook") or {}
    bens = [b for b in (s.get("benefits") or []) if b and b.get("narration")][:3]
    if len(bens) < 2:
        raise RuntimeError("대본 장면이 부족합니다")
    return {
        "hook": {"lines": lines(hook.get("lines")), "narration": clean(hook.get("narration"), 40),
                 "image": idx(hook.get("image"), 0)},
        "benefits": [{"lines": lines(b.get("lines")), "narration": clean(b.get("narration"), 40),
                      "image": idx(b.get("image"), (i + 1) % n)} for i, b in enumerate(bens)],
        "proof_image": idx(s.get("proof_image"), 0),
        "price_image": idx(s.get("price_image"), 0),
        "cta_image": idx(s.get("cta_image"), 0),
        "price_label": clean(s.get("price_label"), 12),
        "youtube_title": clean(s.get("youtube_title"), 70) or p["title"][:60],
        "hashtags": ["#" + re.sub(r"[^0-9A-Za-z가-힣]", "", h) for h in (s.get("hashtags") or [])
                     if re.sub(r"[^0-9A-Za-z가-힣]", "", h)][:5],
    }


# ---------------------------------------------------------------- ElevenLabs 음성
EL = "https://api.elevenlabs.io"


def voice_id() -> str:
    vid = os.environ.get("ELEVENLABS_VOICE_ID", "").strip()
    if vid:
        return vid
    h = {"xi-api-key": env("ELEVENLABS_API_KEY")}
    mine = requests.get(f"{EL}/v1/voices", headers=h, timeout=30)
    mine.raise_for_status()
    for v in mine.json().get("voices", []):
        if config.VOICE_NAME.lower() in v.get("name", "").lower():
            return v["voice_id"]
    sh = requests.get(f"{EL}/v1/shared-voices", headers=h, timeout=30,
                      params={"search": config.VOICE_NAME, "page_size": 20})
    sh.raise_for_status()
    cands = [v for v in sh.json().get("voices", [])
             if config.VOICE_NAME.lower() in v.get("name", "").lower()]
    if not cands:
        raise SystemExit(f"ElevenLabs에서 '{config.VOICE_NAME}' 목소리를 찾지 못했습니다")
    v = cands[0]
    add = requests.post(f"{EL}/v1/voices/add/{v['public_owner_id']}/{v['voice_id']}", headers=h,
                        json={"new_name": config.VOICE_NAME}, timeout=30)
    add.raise_for_status()
    log("ElevenLabs 목소리 추가:", config.VOICE_NAME)
    return add.json().get("voice_id", v["voice_id"])


def tts(text: str, path: str, vid: str, excited=False) -> None:
    h = {"xi-api-key": env("ELEVENLABS_API_KEY")}
    last = None
    for model in config.TTS_MODELS:
        body = {"text": (("[excited] " if excited else "") + text) if model == "eleven_v3" else text,
                "model_id": model, "language_code": "ko"}
        if model == "eleven_v3":
            body["voice_settings"] = {"stability": 0.5}
        else:
            body["voice_settings"] = {"stability": 0.4, "similarity_boost": 0.8, "style": 0.45,
                                      "speed": 1.08}
        try:
            r = requests.post(f"{EL}/v1/text-to-speech/{vid}", headers=h, json=body, timeout=90,
                              params={"output_format": "mp3_44100_128"})
            r.raise_for_status()
            with open(path, "wb") as fp:
                fp.write(r.content)
            return
        except Exception as e:  # noqa: BLE001
            last = e
            log(f"음성({model}) 실패: {e} {getattr(getattr(e, 'response', None), 'text', '')[:200]}")
    raise last


# ---------------------------------------------------------------- GitHub 릴리스 업로드
def upload_release(no: int, files: list) -> dict:
    tok = env("GITHUB_TOKEN")
    h = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}
    tag = f"video-{no}"
    r = requests.post(f"https://api.github.com/repos/{config.REPO}/releases", headers=h, timeout=30,
                      json={"tag_name": tag, "name": f"{no}번 영상", "body": "리빙로그 자동 제작"})
    if r.status_code == 422:
        r = requests.get(f"https://api.github.com/repos/{config.REPO}/releases/tags/{tag}",
                         headers=h, timeout=30)
    r.raise_for_status()
    rel = r.json()
    urls = {}
    for path, ctype in files:
        name = os.path.basename(path)
        for a in rel.get("assets", []):
            if a["name"] == name:
                requests.delete(a["url"], headers=h, timeout=30)
        with open(path, "rb") as fp:
            up = requests.post(f"https://uploads.github.com/repos/{config.REPO}/releases/"
                               f"{rel['id']}/assets", params={"name": name}, timeout=300,
                               headers={**h, "Content-Type": ctype}, data=fp)
        up.raise_for_status()
        urls[name] = up.json()["browser_download_url"]
    return urls


# ---------------------------------------------------------------- main
def main():
    os.makedirs(WORK, exist_ok=True)
    db = load_db()
    used = {str(x["productId"]) for x in db}
    no = max([x["no"] for x in db] or [0]) + 1
    log(f"{no}번 상품 제작 시작")

    listing, kw = pick_product(used)
    p = product_detail(listing)
    log("선택:", p["title"], "| 별점", p.get("rating"), "| 리뷰", p.get("reviewCount"))
    imgs = download_images(p["images"], os.path.join(WORK, "img"))
    s = gemini_script(p, imgs)
    log("대본:", json.dumps(s, ensure_ascii=False))

    vid = voice_id()
    rating = float(p.get("rating") or 0)
    reviews = int(p.get("reviewCount") or 0)
    price = int(p.get("price") or 0)
    badges = []
    if p.get("discountPercent") and int(p.get("discountPercent") or 0) >= 5:
        badges.append(f"{int(p['discountPercent'])}% 할인")
    if p.get("rocketDelivery"):
        badges.append("로켓배송")
    if p.get("freeShipping"):
        badges.append("무료배송")

    ip = lambda k: imgs[k]["path"]  # noqa: E731
    scenes = [{"type": "hook", "image": ip(s["hook"]["image"]), "lines": s["hook"]["lines"],
               "say": s["hook"]["narration"], "excited": True}]
    for b in s["benefits"]:
        scenes.append({"type": "benefit", "image": ip(b["image"]), "lines": b["lines"],
                       "say": b["narration"]})
    if rating >= 4.0 and reviews >= 50:
        scenes.append({"type": "proof", "image": ip(s["proof_image"]), "rating": rating,
                       "reviews": reviews,
                       "say": f"별점 {rating_words(rating)}에, 리뷰가 {rough_count(reviews)} 개 넘어요."})
    if price > 0:
        label = s["price_label"]
        tail = ", 로켓배송으로 받아요." if p.get("rocketDelivery") else "이에요."
        scenes.append({"type": "price", "image": ip(s["price_image"]), "price": price,
                       "label": label, "badges": badges[:2],
                       "say": f"{label + '가 ' if label else ''}{korean_number(price)} 원{tail}"})
    scenes.append({"type": "cta", "image": ip(s["cta_image"]), "excited": True,
                   "say": f"프로필 링크에서 {korean_number(no)} 번 찾아보세요!"})

    adir = os.path.join(WORK, "audio")
    os.makedirs(adir, exist_ok=True)
    for i, sc in enumerate(scenes):
        sc["audio"] = os.path.join(adir, f"s{i}.mp3")
        with_retry(lambda: tts(sc["say"], sc["audio"], vid, sc.get("excited", False)),
                   what=f"음성 {i}")
    bgm = os.path.join(ROOT, "assets", "bgm.mp3")
    spec = {"no": no, "scenes": scenes, "bgm": bgm if os.path.exists(bgm) else None}
    out = os.path.join(WORK, f"livinglog7_{no}.mp4")
    info = render.render(spec, out, WORK)
    log("렌더링 완료:", info)

    link = partner_link(p)
    title = s["youtube_title"]
    tags = s["hashtags"]
    caption = "\n".join([
        f"[광고] {title}",
        "",
        f"📌 프로필 링크 → {no}번",
        f"🔎 {config.SITE_DOMAIN}/{no}",
        "",
        "쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.",
        "",
        " ".join(["#광고"] + tags),
    ])
    today = dt.datetime.now(KST).strftime("%Y-%m-%d")
    entry = {"no": no, "productId": str(p["productId"]), "name": p["title"], "price": price,
             "rating": rating, "reviews": reviews, "image": imgs[s["cta_image"]]["url"],
             "link": link, "keyword": kw, "date": today, "title": title, "caption": caption,
             "hashtags": tags}

    if os.environ.get("DRY_RUN") == "1":
        log("DRY_RUN: 업로드·사이트 갱신 생략")
        save_json(os.path.join(WORK, "entry.json"), entry)
        return

    urls = upload_release(no, [(out, "video/mp4"), (info["thumbnail"], "image/jpeg")])
    entry["video"] = urls[os.path.basename(out)]
    entry["thumb"] = urls[os.path.basename(info["thumbnail"])]
    db.append(entry)
    save_json(DB, db)
    save_json(os.path.join(DOCS, "latest.json"), {
        "ok": True, "no": no, "productName": p["title"], "addedDate": today,
        "videoUrl": entry["video"], "youtubeTitle": f"{title} #shorts"[:100],
        "caption": caption, "hashtags": tags, "link": link})
    site_build.build(db)
    log(f"{no}번 완료")


if __name__ == "__main__":
    main()
