import time
import traceback
from datetime import datetime
import pytz
from src.traders.kr_trader import KoreaTrader
from src.traders.us_trader import USTrader
from src.telegram_bot import send_telegram_msg

class MainController:
    def __init__(self, auth_manager):
        self.auth_manager = auth_manager
        self.kr_trader = KoreaTrader(auth_manager)
        self.us_trader = USTrader(auth_manager)
        
        # 상태 플래그 (중복 실행 방지)
        self.is_kr_selected = False 
        self.is_us_selected = False

        # ✅ 보고서 중복 발송 방지용 플래그 (YYYY-MM-DD 형태로 저장)
        self.last_kr_morning_report = None
        self.last_kr_close_report = None

    def get_market_status(self):
        now = datetime.now(pytz.timezone('Asia/Seoul'))
        hm = int(now.strftime("%H%M"))

        if now.weekday() >= 5: # 토, 일
            return "IDLE"
        
        # [변경] KR_PREPARE 단계 삭제 (더 이상 아침에 종목 발굴 안 함)
        if 900 <= hm <= 1530:
            return "KR_ACTIVE"
        
        if 2230 <= hm <= 2400 or 0 <= hm <= 600:
            return "US_ACTIVE"
            
        return "IDLE"

    def run(self):
        print("🚀 [System] 통합 트레이딩 봇 가동 (Portfolio Mode)")
        send_telegram_msg("🤖 봇이 실행되었습니다. (자동매매 모니터링 시작)")

        last_msg_time = 0
        
        while True:
            try:
                now = datetime.now(pytz.timezone('Asia/Seoul'))
                today_str = now.strftime("%Y-%m-%d")
                hm = int(now.strftime("%H%M"))

                # ✅ [수정] 평일(월~금)인지 확인 (0:월 ~ 4:금, 5:토, 6:일)
                is_weekday = now.weekday() < 5
                
                # ==========================================
                # 🌅 [한국장] 장 시작 전 목표 보고 (08:30 ~ 08:59)
                # ==========================================
                # 평일(is_weekday)이면서 시간이 맞을 때만 실행
                if is_weekday and 830 <= hm < 900:
                    if self.last_kr_morning_report != today_str:
                        print("📨 [Morning] 목표 포트폴리오 리포트 전송 중...")
                        msg = self.kr_trader.report_targets()
                        send_telegram_msg(msg)
                        self.last_kr_morning_report = today_str # 오늘 보냄 표시
                        print("📨 [Ready] 목표 포트폴리오 리포트 전송완료!")

                # ==========================================
                # 🌙 [한국장] 장 마감 후 결산 보고 (15:35 ~ 16:00)
                # ==========================================
                # 평일(is_weekday)이면서 시간이 맞을 때만 실행
                if is_weekday and 1535 <= hm < 2100:
                    if self.last_kr_close_report != today_str:
                        print("📨 [Closing] 마감 결산 리포트 전송 중...")
                        msg = self.kr_trader.report_balance()
                        send_telegram_msg(msg)
                        self.last_kr_close_report = today_str # 오늘 보냄 표시
                        print("📨 [Closed] 마감 결산 리포트 전송 완료!")


                # ==========================================
                # 🚦 메인 매매 루프
                # ==========================================
                
                status = self.get_market_status()
                
                if status == "KR_ACTIVE":
                    if self.kr_trader:
                        self.kr_trader.run()

                    if time.time() - last_msg_time >= 1800:
                        current_time_str = now.strftime('%H:%M:%S')
                        send_telegram_msg(f"✅ [한국시장 봇 생존신고] 정상 작동 중 ({current_time_str})")
                        
                        # 방금 보냈으니 시간을 갱신 (스톱워치 리셋)
                        last_msg_time = time.time()

                    time.sleep(60) # 1분 대기
                
                elif status == "US_ACTIVE":
                    # self.us_trader.run()
                    print(f"\r🇺🇸 [US] 미국장 시간이지만, 트레이딩 기능을 잠시 껐습니다.", end='')
                    time.sleep(60)
                    
                else:
                    print(f"\r💤 [대기] {now.strftime('%H:%M:%S')} (한국시장, 미국시장 대기 중...)", end='')
                    time.sleep(60)

            except KeyboardInterrupt:
                print("\n🛑 프로그램 종료")
                send_telegram_msg("🛑 봇이 사용자에 의해 종료되었습니다.")
                break
            except Exception as e:
                err_msg = traceback.format_exc()
                print(f"\n🚨 [Error] {err_msg}")
                send_telegram_msg(f"🚨 [치명적 에러] 봇이 멈췄습니다!\n{err_msg[:200]}") # 너무 길면 잘라서 전송
                time.sleep(60)