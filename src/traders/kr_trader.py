import requests
import os
import json
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed # ✅ 병렬 처리

from config import Config
from src.traders.base_trader import BaseTrader
from src.data_manager import load_target_stocks
from src.strategy import get_signal
from src.telegram_bot import send_telegram_msg
import csv

class KoreaTrader(BaseTrader):
    def __init__(self, auth_manager):
        super().__init__(auth_manager)
        self.mode = auth_manager.mode
        self.pending_orders = []
        
        self.is_holiday_checked = False 
        self.is_today_holiday = False
        self.last_holiday_log_time = 0

    # =========================================================
    # 🗓️ 휴장일 확인
    # =========================================================
    def check_is_holiday(self):
        """오늘이 휴장일인지 확인 (3시간 단위 로그)"""
        now = datetime.now()
        today_date = now.strftime("%Y%m%d")
        current_time = int(now.strftime("%H%M"))

        # 1. 시간 체크 (08:50 ~ 15:40)
        if current_time < 850 or current_time > 1540:
            return True

        # 2. 휴장일 여부
        is_holiday = False
        
        if self.mode == 'PAPER':
            if now.weekday() >= 5: is_holiday = True
            # (공휴일 하드코딩 생략)
        else:
            if self.is_holiday_checked:
                is_holiday = self.is_today_holiday
            else:
                # API 호출 (1일 1회)
                if not self.token: self.token = self.auth_manager.get_token()
                
                try:
                    path = "/uapi/domestic-stock/v1/quotations/chk-holiday"
                    headers = {
                        "content-type": "application/json; charset=utf-8",
                        "authorization": f"Bearer {self.token}",
                        "appkey": self.app_key, 
                        "appsecret": self.app_secret,
                        "tr_id": "CTCA0903R", 
                        "custtype": "P"
                    }
                    params = {
                        "BASS_DT": today_date, 
                        "CTX_AREA_NK": "", 
                        "CTX_AREA_FK": ""}
                    
                    # ✅ 세션 사용 (timeout 적용)
                    res = self.session.get(f"{self.url_base}{path}", headers=headers, params=params, timeout=5)
                    data = res.json()
                    
                    if res.status_code == 200 and data['rt_cd'] == '0':
                        info = data['output'][0]
                        if info['opnd_yn'] == 'Y':
                            print(f"   📅 [API] 오늘은 실전 영업일입니다. ({today_date})")
                            self.is_today_holiday = False
                            is_holiday = False
                        else:
                            print(f"   ⛔ [API] 오늘은 휴장일입니다. ({today_date})")
                            send_telegram_msg(f"   ⛔ [API] 오늘은 휴장일입니다. ({today_date})")
                            self.is_today_holiday = True
                            is_holiday = True
                        self.is_holiday_checked = True
                    else:
                        is_holiday = False # 에러 시 영업일 가정
                except:
                    is_holiday = False

        # 3. 로그 도배 방지
        if is_holiday:
            if time.time() - self.last_holiday_log_time > 10800:
                print(f"⛔ [Circuit Breaker] 오늘은 휴장일입니다. KR 트레이딩을 멈춥니다. (3시간 대기)")
                self.last_holiday_log_time = time.time()
            return True

        return False
    # ==================================================================
    # [Core] 통합 잔고 조회 (실전/모의 이원화)
    # ==================================================================
    def get_balance(self):
        """
        [통합 잔고 조회]
        - PAPER(모의): 기존 '주식잔고조회' 사용 (안전성 우선)
        - REAL(실전): '실현손익신규' API 사용 (보유+실현손익 통합 조회)
        """
        
        if self.mode == 'PAPER':
            return self._get_balance_paper()

        path = "/uapi/domestic-stock/v1/trading/inquire-balance-rlz-pl"
        tr_id = "TTTC8494R" # 실전투자 전용 (모의투자는 미지원하므로 고정)

        headers = {
            "authorization": f"Bearer {self.token}", 
            "appkey": self.app_key, 
            "appsecret": self.app_secret, 
            "tr_id": tr_id
        }
        
        # 실현손익조회 API 파라미터 (전체 조회: 00)
        params = {
                "CANO": self.account_no,
                "ACNT_PRDT_CD": "01",
                "AFHR_FLPR_YN": "N",
                "OFL_YN": "N",
                "INQR_DVSN": "00",
                "UNPR_DVSN": "01",
                "FUND_STTL_ICLD_YN": "N",
                "FNCG_AMT_AUTO_RDPT_YN": "N",
                "PRCS_DVSN": "00",
                "COST_ICLD_YN": "",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": ""
            }

        try:
            res = self.session.get(f"{self.url_base}{path}", headers=headers, params=params, timeout=5)
            data = res.json()

            if data['rt_cd'] != '0':
                print(f"❌ [{self.mode}] 잔고 조회 실패: {data['msg1']}")
                return 0, 0, {}, {}, {}
            
            elif data['rt_cd'] == '0':
                out1 = data['output1'] # 종목별 상세 (보유 + 매매분)
                out2 = data['output2'][0] # 계좌 합계
                
                # 1. 계좌 요약 데이터 파싱               
                total_cash = float(out2.get('prvs_rcdl_excc_amt', 0)) # 2일 후 예수금
                total_asset = float(out2.get('tot_evlu_amt', 0)) # 주식 총 평가금

                # 실현손익 등 요약 정보
                balance_summary = {
                    "realized_profit": float(out2.get('rlzt_pfls', 0)), # 모의는 없을 수 있음
                    "eval_profit": float(out2.get('evlu_pfls_smtl_amt', 0)),
                    "total_asset": total_asset,
                    "deposit": total_cash
                }
            
                holdings = {}
                details = {}
            
                for item in out1:
                    code = item['pdno']
                    qty = int(item['hldg_qty'])
                    
                    if qty > 0:
                        holdings[code] = qty
                    
                    # 상세 정보 저장
                    details[code] = {
                        'name': item['prdt_name'],
                        'qty': qty,
                        'profit_rate': float(item['evlu_pfls_rt']),
                        'eval_amt': float(item['evlu_amt']),
                        'profit_amt': float(item['evlu_pfls_amt']),
                        'avg_price': float(item['pchs_avg_pric']),
                        'current_price': float(item['prpr']),
                        'realized_pl': float(item.get('rlzt_pfls', 0)) # 실전만 존재
                    }
                        
                return total_asset, total_cash, holdings, details, balance_summary
            else:
                print(f"❌ [KR-Real] 잔고 조회 실패: {data['msg1']}")
                return 0.0, 0.0, {}, {}, {}
                
        except Exception as e:
            print(f"⚠️ [KR-Real] 통합 잔고 에러: {e}")
            return 0.0, 0.0, {}, {}, {}
        
    def _get_balance_paper(self):
        path = "/uapi/domestic-stock/v1/trading/inquire-balance"
        tr_id = "VTTC8434R" if self.mode == 'PAPER' else "TTTC8434R"
        
        headers = {
            "authorization": f"Bearer {self.token}", "appkey": self.app_key, "appsecret": self.app_secret, "tr_id": tr_id
        }
        params = {
            "CANO": self.account_no, 
            "ACNT_PRDT_CD": "01", 
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "N", 
            "INQR_DVSN": "02", 
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N", 
            "FNCG_AMT_AUTO_RDPT_YN": "N", 
            "PRCS_DVSN": "01", 
            "CTX_AREA_FK100": "", 
            "CTX_AREA_NK100": ""
        }
        
        try:
            res = self.session.get(f"{self.url_base}{path}", headers=headers, params=params, timeout=5)
            data = res.json()
            
            if data['rt_cd'] == '0':
                out2 = data['output2'][0]

                total_asset = float(out2.get('tot_evlu_amt', 0)) # 총 자산 (API 값 우선)
                
                balance_summary = {
                    "realized_profit": float(out2.get('rlzt_pfls_amt', 0)),  # 실현 손익
                    "eval_profit": float(out2.get('evlu_pfls_smtl_amt', 0)),  # 평가 손익
                    "today_profit": float(out2.get('asst_icdc_amt', 0)),     # 당일 자산 변동분
                    "deposit": float(out2.get('dnca_tot_amt', 0))
                }

                holdings = {}
                details = {}
                
                for item in data['output1']:
                    qty = int(item['hldg_qty'])
                    if qty > 0:
                        code = item['pdno']
                        holdings[code] = qty
                        details[code] = {
                            "name": item['prdt_name'], "qty": qty,
                            "eval_amt": float(item['evlu_amt']),
                            "profit_rate": float(item['evlu_pfls_rt']), 
                            "profit_amt": float(item['evlu_pfls_amt']),
                            'avg_price': float(item['pchs_avg_pric']),
                            'current_price': float(item['prpr']),
                            "realized_pl": 0 # ✅ [핵심] 모의투자는 이 키가 없으므로 0으로 강제 할당
                        }
                real_cash = float(out2.get('dnca_tot_amt', 0))
                return total_asset, real_cash, holdings, details, balance_summary
            else:
                print(f"❌ [KR] 잔고 조회 실패: {data['msg1']}")
                return 0.0, 0.0, {}, {}, {}
        except Exception as e:
            print(f"⚠️ [KR] 잔고 로직 에러: {e}")
            return 0.0, 0.0, {}, {}, {}

    def get_current_price(self, code):
        path = "/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = {
            "authorization": f"Bearer {self.token}", 
            "appkey": self.app_key, 
            "appsecret": self.app_secret, 
            "tr_id": "FHKST01010100"
        }
        params = {"fid_cond_mrkt_div_code": "J", 
                  "fid_input_iscd": code}
        try:
            res = self.session.get(f"{self.url_base}{path}", headers=headers, params=params, timeout=5)
            if res.status_code == 200 and res.json()['rt_cd'] == '0':
                return int(res.json()['output']['stck_prpr'])
        except Exception as e:
            print(f"⚠️ [Price Error] {code}: {e}")
        return None

    def get_daily_data(self, code):
        """[일봉] 세션 적용 + 타임아웃 2초 (병렬 처리용)"""
        path = "/uapi/domestic-stock/v1/quotations/inquire-daily-price"
        headers = {
            "authorization": f"Bearer {self.token}", 
            "appkey": self.app_key, 
            "appsecret": self.app_secret, 
            "tr_id": "FHKST01010400"
        }
        params = {
            "fid_cond_mrkt_div_code": "J", 
            "fid_input_iscd": code, 
            "fid_input_cnt_1": "100", 
            "fid_org_adj_prc": "1", 
            "fid_period_div_code": "D"
        }
        try:
            res = self.session.get(f"{self.url_base}{path}", headers=headers, params=params, timeout=5)
            if res.status_code == 200 and res.json()['rt_cd'] == '0':
                items = res.json().get('output', [])
                if items:
                    print(f"   📊 [Data] {code} 일봉 {len(items)}일치 수신")
                    return [{
                        "Date": r['stck_bsop_date'], "Close": float(r['stck_clpr']),
                        "Open": float(r['stck_oprc']), "High": float(r['stck_hgpr']),
                        "Low": float(r['stck_lwpr']), "Volume": int(r['acml_vol'])
                    } for r in items]
            else:
                # 🚨 실패 시 에러 메시지 출력
                msg = res.json().get('msg1', 'Unknown Error')
                print(f"   ❌ [Data Fail] {code} 조회 실패: {msg}")
                return []
        except Exception as e:
            print(f"   ⚠️ [Data Error] {code}: {e}")
            return []

    # ==================================================================
    # [Order] 주문 및 취소
    # ==================================================================
    def send_order(self, code, side, price, qty):
        """[한국] 주문 전송 (성공 시 주문번호 반환)"""
        path = "/uapi/domestic-stock/v1/trading/order-cash"
        tr_id = ("VTTC0012U" if side == 'BUY' else "VTTC0011U") if self.mode == 'PAPER' else ("TTTC0012U" if side == 'BUY' else "TTTC0011U")
        
        print(f"   📡 [Sending] {side} {code} {qty}주 (시장가)")

        data = {
            "CANO": self.account_no, "ACNT_PRDT_CD": "01", "PDNO": code,
            "ORD_DVSN": "01", "ORD_QTY": str(qty), "ORD_UNPR": "0"
        }
        headers = {
            "authorization": f"Bearer {self.token}", "appkey": self.app_key, "appsecret": self.app_secret,
            "tr_id": tr_id, "hashkey": self.auth_manager.get_hashkey(data)
        }
        
        try:
            res = self.session.post(f"{self.url_base}{path}", headers=headers, data=json.dumps(data), timeout=2)
            if res.status_code == 200 and res.json()['rt_cd'] == '0':
                odno = res.json()['output']['KRX_FWDG_ORD_ORGNO'] # 주문번호
                time.sleep(0.5) 
                print(f"   ✅ [Accepted] 주문 접수 완료 (No: {odno})")
                return odno # ✅ True 대신 주문번호 반환
            else:
                msg = res.json().get('msg1', '')
                # ✅ [핵심] 휴장일/영업일 에러 감지
                if "영업일" in msg or "휴장" in msg or "장운영" in msg:
                    print(f"   😴 [Holiday] 휴장일/장운영 시간 아님 감지!")
                    return 'HOLIDAY'
                print(f"   ❌ [Failed] 주문 실패: {res.json()['msg1']}")
                return None
        except Exception as e:
            print(f"   ⚠️ [API Error] {e}")
            return None

    def cancel_order(self, order_no, code, qty):
        """[한국] 미체결 주문 취소"""
        print(f"   🗑️ [Canceling] 주문 {order_no} 취소 요청...")
        
        path = "/uapi/domestic-stock/v1/trading/order-rvsecncl"
        tr_id = "VTTC0013U" if self.mode == 'PAPER' else "TTTC0013U" # 취소 주문 TR ID

        data = {
            "CANO": self.account_no, "ACNT_PRDT_CD": "01", 
            "KRX_FWDG_ORD_ORGNO": order_no, # 원주문번호
            "ORGN_ODNO": order_no,
            "ORD_DVSN": "00", # 00: 지정가 (취소는 보통 00 사용)
            "RVSE_CNCL_DVSN_CD": "02", # 02: 전량 취소
            "ORD_QTY": str(qty),
            "ORD_UNPR": "0",
            "QTY_ALL_ORD_YN": "Y" # 잔량 전량 취소 여부
        }
        headers = {
            "authorization": f"Bearer {self.token}", "appkey": self.app_key, "appsecret": self.app_secret,
            "tr_id": tr_id, "hashkey": self.auth_manager.get_hashkey(data)
        }

        try:
            res = self.session.post(f"{self.url_base}{path}", headers=headers, data=json.dumps(data), timeout=2)
            if res.status_code == 200 and res.json()['rt_cd'] == '0':
                print(f"   ✅ [Canceled] 주문 취소 완료")
                return True
            else:
                print(f"   ❌ [Cancel Failed] 취소 실패: {res.json()['msg1']}")
                return False
        except Exception as e:
            print(f"   ⚠️ [Cancel Error] {e}")
            return False

    def save_trade_log(self, type, name, price, qty, reason):
        file_path = "data/trade_history.csv"
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not os.path.exists(file_path):
            with open(file_path, mode='w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['Time', 'Type', 'Name', 'Price', 'Qty', 'Total_Amt', 'Reason'])
        with open(file_path, mode='a', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([now, type, name, price, qty, price*qty, reason])
            
    # ✅ 대기열 관리 (타임아웃 시 자동 취소 추가)
    def clean_pending_orders(self, holdings):
        if not self.pending_orders: return
        current_time = time.time()
        for i in range(len(self.pending_orders) - 1, -1, -1):
            order = self.pending_orders[i]
            
            # 60초 경과 시 취소 시도
            if current_time - order['time'] > 60:
                print(f"      ⏰ [Timeout] {order['code']} 60초 경과 -> 취소 시도")
                # 주문번호(odno)가 있어야 취소 가능
                if 'odno' in order and order['odno']:
                    self.cancel_order(order['odno'], order['code'], 0) # 0은 전량취소
                    send_telegram_msg(f"🗑️ [Timeout] {order['code']} 미체결 주문 취소")
                
                # 취소 여부와 상관없이 대기열에서는 삭제 (다음 사이클에 다시 시도하도록)
                self.pending_orders.pop(i)

    # ==================================================================
    # [Report] 리포트 관련
    # ==================================================================
    def report_targets(self):
        """장 시작 전 목표 보고 (비중 0% 제외)"""
        targets = load_target_stocks("KR")
        if not targets: return "❌ [Error] 타겟 파일 로드 실패"
        
        # 전체 목표 비중 계산
        total_ratio = sum(t.get('target_ratio', 0) for t in targets)
        
        msg = f"☀️ **[오늘의 목표 포트폴리오 (KR)]**\n🎯 목표 비중: {total_ratio*100:.1f}%\n\n"
        
        # 🚨 [수정] 비중이 0보다 큰 것만 리스트에 담아서 출력
        valid_targets = [t for t in targets if t.get('target_ratio', 0) > 0]
        
        if valid_targets:
            for t in valid_targets:
                msg += f"🔹 {t['name']} ({t['code']}): {t.get('target_ratio',0)*100:.1f}%\n"
        else:
            msg += "   (매수 목표 종목 없음)\n"
            
        return msg
    
    def report_balance(self):
        """장 마감 후 결산 보고 (수익률 순 정렬 적용)"""
        self.refresh_token()
        total_asset, total_cash, holdings, details, balance_summary = self.get_balance()
        
        realized = balance_summary.get('realized_profit', 0)
        eval_profit = balance_summary.get('eval_profit', 0) 
        today_profit = realized + eval_profit
        
        msg = "🌙 **[장 마감 결산 보고 (KR)]**\n"
        msg += f"💰 총 자산: {total_asset:,.0f}원\n"
        msg += f"💵 예수금: {total_cash:,.0f}원\n"
        msg += "-" * 28 + "\n"
        msg += f"💸 실현손익: {realized:+,.0f}원 (확정)\n"
        msg += f"📈 평가손익: {eval_profit:+,.0f}원 (미실현)\n"
        msg += f"🔥 **오늘수익: {today_profit:+,.0f}원** (종합)\n"
        msg += "-" * 28 + "\n"
        
        if details:
            msg += "**[종목별 상세 (수익률 순)]**\n"
            
            # 1. 보유 중인 종목만 추려서 리스트 생성
            holding_list = []
            for code, info in details.items():
                if info['qty'] > 0:
                    # 비중 계산 미리 수행
                    info['weight'] = (info['eval_amt'] / total_asset) * 100
                    info['code'] = code # 코드 정보도 딕셔너리에 넣음
                    holding_list.append(info)

            # 🚨 [수정] 수익률(profit_rate) 높은 순서대로 정렬 (내림차순)
            holding_list.sort(key=lambda x: x['profit_rate'], reverse=True)

            if holding_list:
                for info in holding_list:
                    # 수익/손실 아이콘
                    icon = "🔴" if info['profit_rate'] > 0 else "🔵"
                    
                    msg += f"{icon} **{info['name']}** ({info['code']})\n"
                    msg += f"   • 수익: {info.get('profit_amt', 0):+,.0f}원 ({info['profit_rate']:+.2f}%)\n"
                    msg += f"   • 단가: {info['avg_price']:,.0f}원 → {info['current_price']:,.0f}원\n"
                    msg += f"   • 비중: {info['weight']:.1f}% (평가 {info['eval_amt']:,.0f}원)\n"
                    
                    if info.get('realized_pl', 0) != 0:
                        msg += f"   • 금일실현: {info['realized_pl']:+,.0f}원\n"
                    msg += "\n"
            else:
                msg += "   (보유 종목 없음)\n\n"

            # (2) 오늘 전량 매도한 종목 (잔고 0이지만 실현손익 있음)
            sold_stocks_msg = ""
            # 매도한 종목도 리스트로 만들어서 정렬 가능 (여기서는 확정수익 순으로 정렬해봄)
            sold_list = []
            for code, info in details.items():
                if info['qty'] == 0 and info.get('realized_pl', 0) != 0:
                    sold_list.append(info)
            
            sold_list.sort(key=lambda x: x['realized_pl'], reverse=True)

            for info in sold_list:
                sold_stocks_msg += f"🔻 **{info['name']}** (전량매도)\n"
                sold_stocks_msg += f"   💸 확정수익: {info['realized_pl']:+,.0f}원\n"
            
            if sold_stocks_msg:
                msg += "-" * 28 + "\n"
                msg += "**[금일 청산 종목]**\n"
                msg += sold_stocks_msg

        else:
            msg += "보유/매매 내역 없음\n"
            
        return msg
    
    def report_portfolio_status(self):
        """3시간 주기 리포트 (수익률 순 정렬)"""
        total_asset, total_cash, holdings, details, _ = self.get_balance()
        if total_asset == 0:
            print("⚠️ [Skip] 자산 조회 실패로 리포트 전송 생략")
            return
        
        # 타겟 정보를 딕셔너리로 변환 (검색 속도 향상)
        targets = load_target_stocks("KR")
        target_map = {t['code']: t['target_ratio'] for t in targets} if targets else {}

        msg = f"📊 **[중간 점검 (KR)]**\n"
        msg += f"💰 총 자산: {total_asset:,.0f}원\n"
        msg += f"💵 예수금: {total_cash:,.0f}원 (현금비중 {total_cash/total_asset*100:.1f}%)\n"
        msg += "=" * 35 + "\n"

        # 🚨 [수정] 정렬을 위한 리스트 생성
        active_stocks = []
        if details:
            for code, info in details.items():
                if info['qty'] <= 0: continue # 판 종목 제외
                
                # 정보 추가
                info['code'] = code
                info['target_ratio'] = target_map.get(code, 0)
                info['current_ratio'] = (info['eval_amt'] / total_asset) * 100
                active_stocks.append(info)

        # 🚨 [수정] 수익률 높은 순서대로 정렬
        active_stocks.sort(key=lambda x: x['profit_rate'], reverse=True)

        if active_stocks:
            for info in active_stocks:
                target_ratio_pct = info['target_ratio'] * 100
                
                # 아이콘 설정
                icon = "🔴" if info['profit_rate'] > 0 else "🔵"
                if info['profit_rate'] == 0: icon = "⚪"

                msg += f"{icon} **{info['name']}** ({info['code']})\n"
                msg += f"   • 수익: {info['profit_rate']:+.2f}%  |  {info['eval_amt']:,.0f}원\n"
                msg += f"   • 단가: {info['avg_price']:,.0f}원 → {info['current_price']:,.0f}원\n"
                msg += f"   • 비중: {info['current_ratio']:.1f}% (목표 {target_ratio_pct:.0f}%)\n"
                msg += "-" * 35 + "\n"
        else:
            msg += "💤 현재 보유 중인 종목이 없습니다.\n"
        
        # 4. 전송
        send_telegram_msg(msg)
    
    def print_portfolio_status(self, total_asset, total_cash, details, targets):
        """콘솔 출력용 (수익률 순 정렬)"""
        print(f"\n📊 [Portfolio Status] 자산: {total_asset:,.0f}원 | 현금: {total_cash:,.0f}원")
        
        if not details: 
            print("   보유 종목 없음")
            return

        # 🚨 [수정] 출력용 리스트 생성 및 정렬
        print_list = []
        for code, info in details.items():
            if info['qty'] > 0:
                target_r = next((t['target_ratio'] for t in targets if t['code'] == code), 0) * 100
                info['target_r_pct'] = target_r
                info['real_ratio'] = (info['eval_amt'] / total_asset) * 100
                print_list.append(info)
        
        # 수익률 높은 순 정렬
        print_list.sort(key=lambda x: x['profit_rate'], reverse=True)

        if print_list:
            print(f"   {'종목명':<10} | {'수익률':^8} | {'평가금액':^12} | {'비중':^6}")
            print("-" * 50)
            for info in print_list:
                print(f"   {info['name']:<10} | {info['profit_rate']:>6.2f}% | {info['eval_amt']:>11,.0f}원 | {info['real_ratio']:>5.1f}% (목{info['target_r_pct']:.0f}%)")
        else:
            print("   보유 종목 없음 (전량 매도 상태)")
        print("-" * 50)

    # ==================================================================
    # [Main Logic] 봇 실행
    # ==================================================================
    def run(self):
        # 1. 봇 시작 시 휴장일 체크 (가장 먼저 실행!)
        # 오늘이 휴장일이면 바로 함수를 종료시켜 봇을 재웁니다.
        if self.check_is_holiday():
            return # 여기서 종료!
        
        print("\n" + "="*50 + f"\n🚀 [KoreaTrader] 사이클 시작 ({datetime.now().strftime('%H:%M:%S')})\n" + "="*50)
        self.refresh_token()
        
        targets = load_target_stocks("KR")
        if not targets: 
            print("🚨 [System] 타겟 종목 파일이 비어있거나 로드 실패.")
            return
        
        total_asset, total_cash, holdings, details, _ = self.get_balance()

        # 2. 대기 주문 정리 (타임아웃 시 취소)
        self.clean_pending_orders(holdings)

        # ==================================================================
        # 🛑 [NEW] 과매수 방지 로직 (목표 달성 시 미체결 매수 취소)
        # ==================================================================
        for t in targets:
            code = t['code']
            target_ratio = t.get('target_ratio', 0)
            target_amt = total_asset * target_ratio # 목표 금액
            
            # 현재 보유 평가액
            current_amt = details.get(code, {}).get('eval_amt', 0)
            
            # 대기 중인 매수 주문 찾기
            pending_buys = [o for o in self.pending_orders if o['code'] == code and o['type'] == 'BUY']
            
            if pending_buys:
                pending_amt = sum(o.get('amt', 0) for o in pending_buys)
                
                # (보유액 + 대기액)이 목표액을 10% 초과하면 -> 대기 주문 취소!
                if (current_amt + pending_amt) > (target_amt * 1.1):
                    print(f"   🚨 [Overbuy Guard] {t['name']} 목표 비중 충족 예상 -> 미체결 매수 취소")
                    
                    # 대기 중인 주문들 취소 실행
                    for order in pending_buys:
                        if 'odno' in order:
                            self.cancel_order(order['odno'], code, 0) # 0: 전량 취소
                            send_telegram_msg(f"🛡️ [과매수 방지] {t['name']} 미체결 취소 (목표 달성)")
                    
                    # 큐 정리
                    self.pending_orders = [o for o in self.pending_orders if o not in pending_buys]
                    time.sleep(0.5)
        # ==================================================================

        # 3. Cleanup
        current_time = time.time()
        target_codes = set([t['code'] for t in targets])
        for held_code, qty in holdings.items():
            if held_code not in target_codes:
                if any(p['code'] == held_code for p in self.pending_orders): continue
                clean_price = self.get_current_price(held_code)
                if not clean_price: continue 
                
                print(f"🧹 [Cleanup] 제외된 종목 발견: {held_code} -> 전량 매도")
                odno = self.send_order(held_code, 'SELL', clean_price, qty) # odno 반환됨
                if odno:
                    self.save_trade_log("Sell(Cleanup)", held_code, clean_price, qty, "타겟제외")
                    send_telegram_msg(f"🧹 [Cleanup] {held_code} 전량 매도 완료")
                    self.pending_orders.append({'code': held_code, 'type': 'SELL', 'time': time.time(), 'odno': odno})
                    total_cash += (qty * clean_price) 
                time.sleep(0.5)

        # ------------------------------------------------------------------
        # 4. [Parallel] 차트 데이터 갱신 (누락 종목 재시도 로직 강화)
        # ------------------------------------------------------------------
        is_regular_update = (current_time - self.last_chart_update_time) > self.CHART_REFRESH_INTERVAL
        
        # 갱신할 대상 선정
        targets_to_fetch = []
        if is_regular_update:
            targets_to_fetch = targets
        else:
            for t in targets:
                if t['code'] not in self.market_data_cache:
                    targets_to_fetch.append(t)

        # 병렬 요청
        if targets_to_fetch:
            if is_regular_update:
                print(f"\n🔄 [Update] 차트 데이터 정기 갱신 중... (전체)")
                self.last_chart_update_time = current_time 
            else:
                print(f"\n⚠️ [Retry] 데이터 누락 종목 재시도 중... ({len(targets_to_fetch)}개)")

            def fetch_job(target):
                return target['code'], self.get_daily_data(target['code'])

            # 한국장은 TPS 제한이 있으므로 max_workers를 5 정도로 유지
            with ThreadPoolExecutor(max_workers=5) as executor:
                future_to_stock = {executor.submit(fetch_job, t): t for t in targets_to_fetch}
                
                for future in as_completed(future_to_stock):
                    try:
                        code, data = future.result()
                        if data: self.market_data_cache[code] = data
                    except: pass

        # 5. 자금 관리
        min_cash_ratio = getattr(Config, 'MIN_CASH_RATIO', 0.01)
        locked_cash = 0
        for p in self.pending_orders:
            if p['type'] == 'BUY': locked_cash += p.get('amt', 0)
        min_cash_needed = total_asset * min_cash_ratio
        investable_cash = total_cash - min_cash_needed - locked_cash
        if investable_cash < 0: investable_cash = 0

        self.print_portfolio_status(total_asset, total_cash, details, targets)
        print(f"   💰 [Money] 보유: {total_cash:,.0f}원 | 최소보유: {min_cash_needed:,.0f}원 | 👉 가용: {investable_cash:,.0f}원")
        print("-" * 60)

        # 6. 매매 루프
        for t in targets:
            code = t['code']
            name = t['name']
            
            if any(p['code'] == code for p in self.pending_orders): continue
            
            # [Step 1] 현재가 조회
            current_price = self.get_current_price(code)
            if not current_price: continue 
            
            # [Step 2] 리밸런싱
            qty_held = holdings.get(code, 0)
            target_amt = total_asset * t.get('target_ratio', 0)
            current_amt = qty_held * current_price

            if qty_held > 0 and current_amt > (target_amt * 1.2):
                excess_amt = current_amt - target_amt
                sell_qty = int(excess_amt // current_price)
                if sell_qty > 0:
                    print(f"   ⚖️ [Rebalance] {name} 비중 초과 -> {sell_qty}주 매도")
                    odno = self.send_order(code, 'SELL', current_price, sell_qty)
                    if odno == 'HOLIDAY':
                        print("   🛑 [Stop] 휴장일이므로 한국장 매매를 오늘 중단합니다.")
                        return "HOLIDAY" # 컨트롤러에게 보고
                    elif odno:
                        self.save_trade_log("Sell(Rebalance)", name, current_price, sell_qty, "비중초과")
                        send_telegram_msg(f"⚖️ [리밸런싱] {name} 매도: {sell_qty}주")
                        self.pending_orders.append({'code': code, 'type': 'SELL', 'time': time.time(), 'amt': 0, 'odno': odno})
                        total_cash += (sell_qty * current_price)
                        investable_cash += (sell_qty * current_price)
                        time.sleep(0.5)
                    continue
            
            # [Step 3] 차트 데이터 확인
            if code not in self.market_data_cache: continue

            chart_data = self.market_data_cache[code][:] 
            chart_data[-1]['Close'] = float(current_price)
            
            df = self.calculate_indicators(chart_data)
            if df.empty: continue
            
            signal, reason, _ = get_signal(t.get('strategy'), df.iloc[-1], df.iloc[-2], t.get('setting'))
            
            # [B] 매수
            if signal == 'buy':
                needed = target_amt - current_amt
                amt = min(needed, investable_cash)
                qty = int(amt // current_price)
                
                if qty > 0:
                    print(f"   ⚡ [Buy Signal] {name} {qty}주")
                    odno = self.send_order(code, 'BUY', current_price, qty)

                    # ✅ [핵심] 휴장일 신호가 오면 즉시 리턴!
                    if odno == 'HOLIDAY':
                        print("   🛑 [Stop] 휴장일이므로 한국장 매매를 오늘 중단합니다.")
                        return "HOLIDAY"  # 컨트롤러에게 보고
                    
                    elif odno:
                        self.save_trade_log("Buy", name, current_price, qty, reason)
                        send_telegram_msg(f"🚀 [매수 체결] {name} {qty}주 (@ {current_price:,}원), 이유 {reason}")
                        # ✅ odno 추가 저장
                        self.pending_orders.append({'code': code, 'type': 'BUY', 'time': time.time(), 'amt': qty*current_price, 'odno': odno})
                        total_cash -= (qty * current_price)
                        investable_cash -= (qty * current_price)
                        time.sleep(0.5)

            # [C] 매도
            elif signal == 'sell' and qty_held > 0:
                print(f"   ⚡ [Sell Signal] {name} {qty_held}주")
                odno = self.send_order(code, 'SELL', current_price, qty_held)

                if odno == 'HOLIDAY':
                    print("   🛑 [Stop] 휴장일이므로 한국장 매매를 오늘 중단합니다.")
                    return "HOLIDAY" # 컨트롤러에게 보고
                
                elif odno:
                    self.save_trade_log("Sell", name, current_price, qty_held, reason)
                    send_telegram_msg(f"💧 [매도 체결] {name} {qty_held}주 (전량), 이유 {reason}")
                    self.pending_orders.append({'code': code, 'type': 'SELL', 'time': time.time(), 'amt': 0, 'odno': odno})
                    total_cash += (qty_held * current_price)
                    investable_cash += (qty_held * current_price)
                    time.sleep(0.5)

        time.sleep(0.3)
        return "NORMAL"