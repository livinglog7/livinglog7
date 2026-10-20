"""livinglog7.com 정적 사이트 생성 (GitHub Pages, docs 폴더).

- /            : 전체 상품 목록 + 번호/이름 검색
- /N/          : 영상 속 N번 상품 페이지 (쿠팡 파트너스 링크 버튼)
"""
from __future__ import annotations

import html
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402

DISCLOSURE = "이 페이지는 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."

HEAD = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><meta name="description" content="{desc}">
<meta property="og:title" content="{title}"><meta property="og:description" content="{desc}">
{og_image}<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%231F1A17'/%3E%3Ctext x='32' y='44' font-size='34' text-anchor='middle' fill='%23F6F1EA' font-family='serif'%3EL%3C/text%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700;900&family=Noto+Serif+KR:wght@600;700&display=swap" rel="stylesheet">
<style>
:root{{--bg:#F6F1EA;--card:#FFFDF9;--ink:#1F1A17;--sub:#857A70;--line:#E7DED3;--acc:#C2410C;--brown:#6E5440}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#171412;--card:#211D1A;--ink:#F3ECE4;--sub:#A69A8F;--line:#36302B;--acc:#F07A3A;--brown:#C7A88C}}}}
:root[data-theme="dark"]{{--bg:#171412;--card:#211D1A;--ink:#F3ECE4;--sub:#A69A8F;--line:#36302B;--acc:#F07A3A;--brown:#C7A88C}}
*{{box-sizing:border-box}}html{{-webkit-text-size-adjust:100%}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:"Noto Sans KR",system-ui,sans-serif;line-height:1.5;word-break:keep-all;overflow-wrap:anywhere}}
a{{color:inherit}}.wrap{{max-width:980px;margin:0 auto;padding:0 16px}}
.top{{padding:34px 0 10px;text-align:center}}.brand{{font-family:"Noto Serif KR",serif;font-size:30px;font-weight:700;letter-spacing:.06em;text-decoration:none}}
.tag{{margin:6px 0 0;color:var(--sub);font-size:14px}}
.note{{margin:14px auto 0;max-width:640px;font-size:12px;color:var(--sub);text-align:center}}
.ad{{display:inline-block;font-size:11px;font-weight:700;border:1px solid var(--sub);color:var(--sub);border-radius:4px;padding:0 5px;margin-right:6px;vertical-align:1px}}
.search{{position:sticky;top:0;z-index:5;background:var(--bg);padding:14px 0}}
.search input{{width:100%;font:inherit;font-size:17px;padding:14px 20px;border:1px solid var(--line);border-radius:999px;background:var(--card);color:var(--ink);outline:none}}
.search input:focus{{border-color:var(--brown)}}
.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;padding-bottom:40px}}
@media(min-width:720px){{.grid{{grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}}}}
.item{{display:block;background:var(--card);border:1px solid var(--line);border-radius:18px;overflow:hidden;text-decoration:none}}
.ph{{position:relative;aspect-ratio:1;background:#fff}}.ph img{{width:100%;height:100%;object-fit:contain}}
.no{{position:absolute;top:8px;left:8px;background:var(--acc);color:#fff;font-weight:900;font-size:15px;min-width:36px;height:36px;padding:0 9px;border-radius:999px;display:flex;align-items:center;justify-content:center}}
.tx{{padding:10px 12px 14px}}.nm{{margin:0;font-size:14px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;min-height:2.9em}}
.pr{{margin:6px 0 0;font-weight:900}}.empty{{text-align:center;color:var(--sub);padding:40px 0}}
.detail{{max-width:560px;margin:0 auto;padding:8px 0 48px}}
.hero{{background:#fff;border-radius:22px;overflow:hidden;border:1px solid var(--line);position:relative}}.hero img{{width:100%;display:block;aspect-ratio:1;object-fit:contain}}
.hero .no{{top:14px;left:14px;font-size:20px;min-width:52px;height:52px}}
h1{{font-size:21px;line-height:1.4;margin:18px 0 6px}}.meta{{color:var(--sub);font-size:14px;margin:0}}
.price{{font-size:30px;font-weight:900;margin:10px 0 2px}}.small{{font-size:12px;color:var(--sub)}}
.btn{{display:block;margin:20px 0 10px;text-align:center;background:var(--ink);color:var(--bg);text-decoration:none;font-weight:900;font-size:18px;padding:17px;border-radius:16px}}
.back{{display:block;text-align:center;color:var(--sub);font-size:14px;margin-top:8px}}
</style></head><body>"""


def esc(s) -> str:
    return html.escape(str(s or ""), quote=True)


def won(n) -> str:
    return f"{int(n):,}원" if n else ""


def detail_page(p: dict) -> str:
    title = f"{p['no']}번 · {p['name']} | 리빙로그"
    head = HEAD.format(title=esc(title), desc=esc(f"리빙로그 영상 속 {p['no']}번 살림템"),
                       og_image=f'<meta property="og:image" content="{esc(p.get("image"))}">')
    stars = f"★ {p['rating']:.1f} · 리뷰 {int(p['reviews']):,}개" if p.get("reviews") else ""
    return head + f"""
<div class="wrap"><header class="top"><a class="brand" href="/">리빙로그</a>
<p class="note"><span class="ad">광고</span>{esc(DISCLOSURE)}</p></header>
<main class="detail">
<div class="hero"><span class="no">{p['no']}</span><img src="{esc(p.get('image'))}" alt="{esc(p['name'])}"></div>
<h1>{esc(p['name'])}</h1>
<p class="meta">{esc(stars)}</p>
<p class="price">{won(p.get('price'))}</p>
<p class="small">{esc(p.get('date'))} 기준 가격이에요. 실제 가격은 쿠팡에서 확인해 주세요.</p>
<a class="btn" href="{esc(p['link'])}" rel="sponsored nofollow noopener" target="_blank">쿠팡에서 보기</a>
<a class="back" href="/">다른 살림템 둘러보기</a>
</main></div></body></html>"""


def index_page(items: list) -> str:
    head = HEAD.format(title="리빙로그 · 영상 속 살림템", desc="리빙로그 영상에 나온 살림템을 번호로 찾아보세요",
                       og_image="")
    cards = []
    for p in sorted(items, key=lambda x: -x["no"]):
        key = esc(f"{p['no']} {p['name']} {p.get('keyword', '')}".lower())
        cards.append(f"""<a class="item" href="/{p['no']}/" data-no="{p['no']}" data-s="{key}">
<div class="ph"><span class="no">{p['no']}</span><img loading="lazy" src="{esc(p.get('image'))}" alt=""></div>
<div class="tx"><p class="nm">{esc(p['name'])}</p><p class="pr">{won(p.get('price'))}</p></div></a>""")
    empty = "검색 결과가 없어요" if items else "곧 첫 살림템이 올라와요"
    return head + f"""
<div class="wrap"><header class="top"><a class="brand" href="/">리빙로그</a>
<p class="tag">영상 속 살림템을 번호로 찾아보세요</p>
<p class="note"><span class="ad">광고</span>{esc(DISCLOSURE)}</p></header>
<div class="search"><input id="q" type="search" inputmode="search" autocomplete="off" placeholder="영상 속 번호 또는 이름 (예: 12)"></div>
<div class="grid" id="g">{''.join(cards)}</div>
<p class="empty" id="e"{' hidden' if items else ''}>{empty}</p></div>
<script>
var q=document.getElementById('q'),cs=[].slice.call(document.querySelectorAll('.item')),e=document.getElementById('e');
q.addEventListener('input',function(){{var v=q.value.trim().toLowerCase(),n=0;
cs.forEach(function(c){{var ok=!v||(/^\\d+$/.test(v)?c.getAttribute('data-no')===v:c.getAttribute('data-s').indexOf(v)>-1);c.style.display=ok?'':'none';if(ok)n++}});
e.hidden=n>0;}});
q.addEventListener('keydown',function(ev){{if(ev.key==='Enter'&&/^\\d+$/.test(q.value.trim())){{var c=document.querySelector('.item[data-no="'+q.value.trim()+'"]');if(c)location.href=c.getAttribute('href')}}}});
</script></body></html>"""


def build(items: list) -> None:
    os.makedirs(DOCS, exist_ok=True)
    with open(os.path.join(DOCS, "index.html"), "w", encoding="utf-8") as fp:
        fp.write(index_page(items))
    for p in items:
        d = os.path.join(DOCS, str(p["no"]))
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as fp:
            fp.write(detail_page(p))
    with open(os.path.join(DOCS, "404.html"), "w", encoding="utf-8") as fp:
        fp.write('<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=/">'
                 '<title>리빙로그</title><body style="background:#F6F1EA">')
    with open(os.path.join(DOCS, "CNAME"), "w") as fp:
        fp.write(config.SITE_DOMAIN + "\n")
    open(os.path.join(DOCS, ".nojekyll"), "w").close()


if __name__ == "__main__":
    db_path = os.path.join(DOCS, "products.json")
    data = json.load(open(db_path, encoding="utf-8")) if os.path.exists(db_path) else []
    build(data)
    print(f"사이트 생성: 상품 {len(data)}개")
