"""기존 영상의 대표 썸네일을 새 통일 디자인으로 다시 만든다 (영상은 건드리지 않음)."""
import io, json, os, re, sys
import requests
from PIL import Image
sys.path.insert(0, os.path.dirname(__file__))
import render
import run

LINES = {
    1: ["분리수거 걱정", "이제 끝"], 2: ["기름기 싹", "설거지 해결"], 3: ["계란 한판이", "싹 정리돼요"],
    4: ["매일 세탁 힘든", "침구 관리 끝"], 5: ["냉장고 정리", "깔끔하게"], 6: ["집안 가득", "향긋한 향기"],
    7: ["옷에 밴 냄새", "포근하게 끝"], 8: ["방 분위기 살리는", "귀여운 무드등"],
    9: ["전자레인지 요리", "이걸로 끝"], 10: ["못 없이 깔끔한", "강력 고정"], 11: ["발 냄새 걱정", "싹 씻어요"],
}
nos = [int(x) for x in os.environ.get("COVER_NOS", "1,2,3,4,5,6,7").split(",")]
items = {x["no"]: x for x in json.load(open("docs/products.json", encoding="utf-8"))}
os.makedirs("work", exist_ok=True)
files = []
for n in nos:
    p = items[n]
    u = re.sub(r"/thumbnails/remote/\d+x\d+ex/", "/thumbnails/remote/1000x1000ex/", p["image"])
    r = requests.get(u, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    if r.status_code != 200:
        r = requests.get(p["image"], timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    ip = f"work/src_{n}.jpg"
    Image.open(io.BytesIO(r.content)).convert("RGB").save(ip, quality=92)
    cv = {"image": ip, "lines": LINES[n], "rating": p["rating"], "reviews": p["reviews"]}
    out = f"work/cover_{n}.jpg"
    render.make_cover(cv, n).convert("RGB").save(out, quality=93)
    files.append((out, "image/jpeg"))
    print("cover", n, out)
if os.environ.get("GITHUB_TOKEN"):
    for n, f in zip(nos, files):
        print(run.upload_release(n, [f]))
