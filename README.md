# 리빙로그 (livinglog7)

매일 오전 9시 37분, 쿠팡 판매 상위 살림템 1개를 골라 세로 광고 영상을 자동으로 만들고
상품 사이트 [livinglog7.com](https://livinglog7.com)에 번호를 붙여 올립니다.

## 흐름
1. `pipeline/run.py` — 키워드 → 쿠팡 판매량순 검색(Apify) → 상품 1개 선택 → 실제 사진 수집
2. Gemini가 사진을 보고 장면 문구 작성 (확인된 정보만)
3. ElevenLabs(Anna Kim)로 음성 생성
4. `pipeline/render.py` — 1080×1920 영상 렌더링 (워터마크 없음)
5. 영상은 GitHub 릴리스(`video-N`)에, 상품 정보는 `docs/products.json`에 저장
6. `pipeline/site_build.py` — `docs/` 정적 사이트 갱신 (GitHub Pages)
7. `docs/latest.json` → 오전 10시대 업로드 작업이 읽어서 Metricool로 인스타·스레드·유튜브 게시

## 비밀값 (Settings → Secrets and variables → Actions)
- `APIFY_TOKEN`, `GEMINI_API_KEY`, `ELEVENLABS_API_KEY`

## 수동 실행
Actions → "매일 숏폼 제작" → Run workflow (dry_run=1 이면 업로드 없이 미리보기만)

설정(키워드·기준)은 `pipeline/config.py`에서 바꿉니다.
