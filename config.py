# config.py
import os
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

class Config:
    # ==========================================
    # 🇰🇷 한국투자증권 설정 (KR: 실전투자)
    # ==========================================
    KR_MODE = "REAL"  # 한국은 고정
    print(f"🚀 [모드] 한국 시장 - 실전투자(REAL) 환경으로 시작합니다.")
    KR_APP_KEY = os.getenv("KI_APP_KEY")
    KR_APP_SECRET = os.getenv("KI_APP_SECRET")
    KR_URL_BASE = os.getenv("KI_BASE_URL")
    KR_ACCOUNT_NO = os.getenv("KI_ACCOUNT_NO")

    # ==========================================
    # 🇺🇸 미국주식 설정 (US: 실전투자)
    # ==========================================
    US_MODE = "REAL"   # 미국은 실전투자 고정
    print(f"🚨 [주의] 미국 시장 - 실전투자(REAL) 환경으로 시작합니다.")
    # 실전 투자는 보통 .env의 KI_ (Korea Investment) 변수를 사용합니다.
    # .env 파일에 KI_APP_KEY 등이 있는지 꼭 확인하세요!
    US_APP_KEY = os.getenv("KI_APP_KEY")
    US_APP_SECRET = os.getenv("KI_APP_SECRET")
    US_URL_BASE = os.getenv("KI_BASE_URL")
    US_ACCOUNT_NO = os.getenv("KI_ACCOUNT_NO")


    # 공통 설정 (계좌번호, ID 등) 
    ACNT_PRDT_CD = os.getenv("my_prod")          # 계좌번호 뒤 2자리 (보통 01)
    HTS_ID = os.getenv("my_htsid")               # HTS ID
    USER_AGENT = os.getenv("my_agent")           # User-Agent

    # 필수값 체크 (키가 비어있으면 에러 발생)
    if not KR_APP_KEY or not KR_APP_SECRET:
        print("⚠️ [Warning] 한국(모의) 투자 키가 .env에 없습니다.")
    
    if not US_APP_KEY or not US_APP_SECRET:
        print("⚠️ [Warning] 미국(실전) 투자 키가 .env에 없습니다. (KI_... 변수 확인)")

    # 텔레그램 설정
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
    TELEGRAM_ID = os.getenv("TELEGRAM_ID")

    # 최소 현금 비율 (0.01 = 1%)
    MIN_CASH_RATIO = 0.01