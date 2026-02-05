from config import Config
from src.auth import AuthManager
from src.traders.us_trader import USTrader

def test_balance():
    print("🇺🇸 [Test] 미국 계좌 잔고 조회 테스트 시작...")
    
    # 1. 인증 관리자 초기화 (미국 계좌 정보)
    auth = AuthManager(
        app_key=Config.US_APP_KEY,
        app_secret=Config.US_APP_SECRET,
        url_base=Config.US_URL_BASE,
        account_no=Config.US_ACCOUNT_NO,
        mode=Config.US_MODE
    )

    # 2. 트레이더 초기화
    trader = USTrader(auth)

    # 3. 잔고 조회 함수 직접 호출 (run() 아님!)
    print("\n📡 API 호출 중...")
    total_asset, total_usd, holdings, details = trader.get_balance()

    portfolio = trader.report_portfolio_status()

    print("\n" + "="*40)
    print(f"💰 결과 확인")
    print(f"   - 총 자산: ${total_asset:,.2f}")
    print(f"   - 보유 현금(USD): ${total_usd:,.2f}")
    print("="*40)
    
    if holdings:
        print(f"📂 [보유 종목 리스트]")
        for code, info in details.items():
            print(f"   🔹 {info['name']} ({code})")
            print(f"      수량: {info['qty']}주")
            print(f"      평가금액: ${info['eval_amt']:,.2f}")
            print(f"      수익률: {info['profit_rate']}%")
            print("-" * 30)
    else:
        print("📂 보유 종목이 없습니다 (0개)")
        print("⚠️ 주의: TQQQ를 샀는데 여기가 비어있으면 아직 해결 안 된 겁니다.")

if __name__ == "__main__":
    test_balance()
    