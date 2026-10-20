"""리빙로그 자동화 설정. 키워드나 기준을 바꾸려면 이 파일만 고치면 된다."""

PARTNER_ID = "AF1629829"  # 쿠팡 파트너스 ID
SITE_DOMAIN = "livinglog7.com"
REPO = "livinglog7/livinglog7"

# 매일 하나씩 돌아가며 쓰는 살림 키워드
KEYWORDS = [
    "수납정리함", "욕실청소용품", "주방정리", "밀폐용기", "빨래건조대",
    "청소포", "디퓨저", "섬유향수", "행주", "침구청소기",
    "주방세제", "수세미", "냉장고정리", "욕실매트", "제습제",
    "옷걸이", "틈새수납장", "욕실선반", "먼지떨이", "물걸레청소기",
    "주방매트", "분리수거함", "세탁망", "수저정리함", "다용도선반",
]

# 상품 선택 기준
MIN_RATING = 4.5
MIN_REVIEWS = 100

# ElevenLabs 목소리 (사장님 선택: Anna Kim)
VOICE_NAME = "Anna Kim"
TTS_MODELS = ["eleven_v3", "eleven_multilingual_v2"]

GEMINI_MODEL = "gemini-2.5-flash"

APIFY_ACTOR = "parsebird~coupang-scraper"
