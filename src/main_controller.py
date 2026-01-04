import time
import traceback
from datetime import datetime
import pytz
from config import Config
from src.auth import AuthManager
from src.traders.kr_trader import KoreaTrader
from src.traders.us_trader import USTrader
from src.telegram_bot import send_telegram_msg

class MainController:
    def __init__(self):
        # 1. 한국장 인증 (모의투자)
        self.kr_auth = AuthManager(
            app_key=Config.KR_APP_KEY,
            app_secret=Config.KR_APP_SECRET,
            url_base=Config.KR_URL_BASE,
            account_no=Config.KR_ACCOUNT_NO,
            mode=Config.KR_MODE
        )
        
        # 2. 미국장 인증 (실전투자)
        self.us_auth = AuthManager(
            app_key=Config.US_APP_KEY,
            app_secret=Config.US_APP_SECRET,
            url_base=Config.US_URL_BASE,
            account_no=Config.US_ACCOUNT_NO,
            mode=Config.US_MODE
        )

        # 3. 트레이더 생성
        self.kr_trader = KoreaTrader(self.kr_auth)
        self.us_trader = USTrader(self.us_auth)
        
        # 보고서 플래그
        self.last_kr_morning_report = None
        self.last_kr_close_report = None
        self.last_us_morning_report = None
        self.last_us_close_report = None

        # ✅ [추가] 휴장일 감지 플래그 (True면 오늘 하루 봇 정지)
        self.is_kr_holiday = False
        self.is_us_holiday = False
        
        # 날짜 변경 감지용
        self.last_date = ""

    def get_market_status(self):
        
        now = datetime.now(pytz.timezone('Asia/Seoul'))
        hm = int(now.strftime("%H%M"))
        if now.weekday() >= 5: # 토, 
            # 단, 토요일 새벽은 미국장이 열려있을 수 있으므로 아래 로직으로 넘어감
            if now.weekday() == 5 and 0 <= hm <= 600:
                pass
            else:
                return "IDLE"
        
        if 900 <= hm <= 1530:
            #return "IDLE"
            return "KR_ACTIVE"
        
        if 2330 <= hm <= 2400 or 0 <= hm <= 600:
            return "US_ACTIVE"


        #return "KR_ACTIVE"

    def run(self):
        print("🚀 [System] 하이브리드 트레이딩 봇 가동 (KR:Paper / US:Real)")
        send_telegram_msg("🤖 하이브리드 봇 실행 (KR:모의 / US:실전)")

        last_kr_msg_time = 0
        last_us_msg_time = 0
        
        while True:
            try:
                now = datetime.now(pytz.timezone('Asia/Seoul'))
                today_str = now.strftime("%Y-%m-%d")
                hm = int(now.strftime("%H%M"))
                weekday = now.weekday() # 0:월 ~ 6:일

                # 평일 확인 (월~금)
                is_weekday = weekday < 5

                # 🔄 [리셋] 날짜가 바뀌면 휴장일 플래그 초기화 (새로운 날이니까 다시 시도)
                if today_str != self.last_date:
                    if self.is_kr_holiday:
                        print(f"📅 [System] 날짜 변경! KR 휴장 플래그 해제")
                        self.is_kr_holiday = False
                    if self.is_us_holiday:
                        print(f"📅 [System] 날짜 변경! US 휴장 플래그 해제")
                        self.is_us_holiday = False
                    self.last_date = today_str
                
                # ==========================================
                # 🌅 [한국장] 장 시작 전 목표 보고 (08:30 ~ 08:59)
                # ==========================================
                if is_weekday and 830 <= hm < 900:
                    if self.last_kr_morning_report != today_str:
                        print("📨 [KR Morning] 목표 포트폴리오 리포트 전송 중...")
                        msg = self.kr_trader.report_targets()
                        send_telegram_msg(msg)
                        self.last_kr_morning_report = today_str
                        print("📨 [Done] 전송 완료")

                # ==========================================
                # 🌙 [한국장] 장 마감 후 결산 보고 (15:35 ~ 16:00)
                # ==========================================
                if is_weekday and 1545 <= hm < 1600:
                    if self.last_kr_close_report != today_str:
                        print("📨 [KR Closing] 마감 결산 리포트 전송 중...")
                        msg = self.kr_trader.report_balance()
                        send_telegram_msg(msg)
                        self.last_kr_close_report = today_str
                        print("📨 [Done] 전송 완료")

                # =========================================================
                # 🇺🇸 [미국장] 리포트링 장 시작 전 목표 보고 (23:00 ~ 23:29)
                # =========================================================
                if is_weekday and 2300 <= hm < 2330:
                    if self.last_us_morning_report != today_str:
                        print("📨 [US Morning] 목표 포트폴리오 리포트 전송 중...")
                        msg = self.us_trader.report_targets()
                        send_telegram_msg(msg)
                        self.last_us_morning_report = today_str
                        print("📨 [Done] 전송 완료")

                # =========================================================
                # 🇺🇸 [미국장] 리포트링 장 마감 후 결산 보고 (06:05 ~ 07:30)
                # =========================================================
                if (is_weekday or weekday == 5) and 605 <= hm < 700:
                    if self.last_us_close_report != today_str:
                        print("📨 [US Closing] 마감 결산 리포트 전송 중...")
                        msg = self.us_trader.report_balance()
                        send_telegram_msg(msg)
                        self.last_us_close_report = today_str
                        print("📨 [Done] 전송 완료")
                    
                # ==========================================
                # 🚦 메인 매매 루프
                # ==========================================
                
                status = self.get_market_status()
                
                if status == "KR_ACTIVE":
                    # ✅ [핵심] 휴장일이 아닐 때만 run() 실행
                    if not self.is_kr_holiday:
                        result = self.kr_trader.run()

                        # 🚨 휴장일 보고를 받으면 플래그 세우기
                        if result == "HOLIDAY":
                            print(f"⛔ [Circuit Breaker] 한국장 휴장일 감지 -> 오늘 KR 트레이딩 종료")
                            self.is_kr_holiday = True
                            send_telegram_msg("⛔ [한국장] 휴장일 감지! 오늘 매매를 종료합니다.")
                        
                        time.sleep(2) # 정상 대기
                    else:
                        # 휴장일이면 그냥 대기 (API 호출 안 함)
                        print(f"\r⛔ [KR] 휴장일 대기 중... ({now.strftime('%H:%M:%S')})", end='')

                    if time.time() - last_kr_msg_time >= 10800:
                        print(f"⏰ [알림] 3시간 정기 포트폴리오 보고 전송 중... ({now.strftime('%H:%M:%S')})")
                        self.kr_trader.report_portfolio_status()
                        last_kr_msg_time = time.time() # 타이머 리셋
                    
                    if not self.is_kr_holiday:
                        print(f"\r [KR] 모니터링 중... ({now.strftime('%H:%M:%S')})", end='')
                        time.sleep(3)
                    else:
                        time.sleep(60) # 휴장일엔 1분 대기
                
                elif status == "US_ACTIVE":
                    if not self.is_us_holiday:
                        result = self.us_trader.run()
                        if result == "HOLIDAY":
                            print(f"⛔ [Circuit Breaker] 미국장 휴장일 감지 -> 오늘 US 트레이딩 종료")
                            self.is_us_holiday = True
                            send_telegram_msg("⛔ [미국장] 휴장일 감지! 오늘 매매를 종료합니다.")
                    else:
                        print(f"\r⛔ [US] 휴장일 대기 중... ({now.strftime('%H:%M:%S')})", end='')

                    # 미국장 생존신고 로직 추가 (미국 타이머 last_us_msg_time 사용)
                    if time.time() - last_us_msg_time >= 10800:
                        print(f"⏰ [알림] 3시간 정기 포트폴리오 보고 전송 중... ({now.strftime('%H:%M:%S')})")
                        self.us_trader.report_portfolio_status()            
                        last_us_msg_time = time.time() # 미국 타이머 리셋
                    
                    # 대기 시간
                    if not self.is_us_holiday:
                        print(f"\r🇺🇸 [US] 모니터링 중... ({now.strftime('%H:%M:%S')})", end='')
                        time.sleep(1)
                    else:
                        time.sleep(60) # 휴장일엔 1분 대기

                # 💤 [휴장 시간]
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
                send_telegram_msg(f"🚨 [치명적 에러] 봇이 멈췄습니다!\n{err_msg[:200]}") 
                time.sleep(60)