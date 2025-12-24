# config.py
import os
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

class Config:
    # ==========================================
    # 🎮 모드 설정 (여기만 바꾸면 됩니다!)
    # 'PAPER' : 모의투자 / 'REAL' : 실전투자
    # ==========================================
    MODE = 'PAPER' 
    # ==========================================

    # 공통 설정 (계좌번호, ID 등) 
    ACNT_PRDT_CD = os.getenv("my_prod")          # 계좌번호 뒤 2자리 (보통 01)
    HTS_ID = os.getenv("my_htsid")               # HTS ID
    USER_AGENT = os.getenv("my_agent")           # User-Agent

    # 모드에 따라 키와 URL을 자동으로 선택하는 로직
    if MODE == 'PAPER':
        print(f"🚀 [모드] 모의투자(PAPER) 환경으로 시작합니다.")
        APP_KEY = os.getenv("paper_APP_KEY")
        APP_SECRET = os.getenv("paper_APP_SECRET")
        URL_BASE = os.getenv("paper_BASE_URL")
        ACCOUNT_NO = os.getenv("paper_ACCOUNT_NO") # 계좌번호 앞 8자리 (모의)
    else:
        print(f"🚨 [주의] 실전투자(REAL) 환경으로 시작합니다.")
        APP_KEY = os.getenv("KI_APP_KEY")
        APP_SECRET = os.getenv("KI_APP_SECRET")
        URL_BASE = os.getenv("KI_BASE_URL")
        ACCOUNT_NO = os.getenv("KI_ACCOUNT_NO") # 계좌번호 앞 8자리 (실전)

    # 필수값 체크 (키가 비어있으면 에러 발생)
    if not APP_KEY or not APP_SECRET:
        raise ValueError(f"❌ Error: {MODE} 모드의 APP_KEY 또는 APP_SECRET이 .env에 없습니다.")
    

    # 텔레그램 설정
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
    TELEGRAM_ID = os.getenv("TELEGRAM_ID")
