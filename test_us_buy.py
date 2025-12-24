import sys
import os

# 모듈 경로 문제 방지를 위해 현재 경로 추가
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.config import Config
from src.auth import AuthManager  # 👈 [변경] TokenManager 대신 AuthManager import
from src.traders.us_trader import USTrader

# ==========================================
# 🧪 미국 주식 매수 테스트 (AuthManager 버전)
# ==========================================

def test_buy():
    # 1. 설정 확인
    print(f"현재 모드: {Config.MODE}")
    if Config.MODE == "REAL":
        print("⚠️ 주의: 실전 투자(REAL) 모드입니다. 실제 자금이 사용됩니다.")
        check = input("진행하시겠습니까? (y/n): ")
        if check.lower() != 'y':
            print("테스트를 종료합니다.")
            return

    # 2. 객체 생성 (AuthManager 사용)
    try:
        auth_manager = AuthManager()  # 👈 여기서 AuthManager를 생성
        us_trader = USTrader(auth_manager) # 👈 Trader에게 넘겨줌
        print("✅ AuthManager 및 USTrader 초기화 성공")
    except Exception as e:
        print(f"❌ 초기화 실패: {e}")
        return

    # 3. 테스트 종목 설정
    # TSLA (테슬라) - 거래소: NASD (나스닥)
    target_code = "TSLA"
    target_exchange = "NASD" 
    
    # 💵 안전한 테스트를 위해 현재가보다 터무니없이 낮은 가격 입력
    # (예: 테슬라가 400불이면 100불에 주문 -> 체결 안 되고 대기만 함)
    target_price = 100.00 
    target_qty = 1

    print(f"\n🚀 [Test] {target_code} ({target_exchange}) 1주를 ${target_price}에 매수 주문합니다...")

    # 4. 매수 실행
    result = us_trader.buy_stock(target_code, target_qty, target_price, exchange=target_exchange)

    if result:
        print("\n🎉 테스트 성공! (주문이 정상적으로 서버에 전송되었습니다)")
    else:
        print("\n😭 테스트 실패! (로그의 에러 메시지를 확인하세요)")

if __name__ == "__main__":
    test_buy()