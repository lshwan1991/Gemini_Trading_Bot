import requests
import json
import time
from datetime import datetime
from config import Config
from src.traders.base_trader import BaseTrader
from src.data_manager import load_target_stocks
from src.strategy import get_signal

class USTrader(BaseTrader):  
    def __init__(self, auth_manager):
        super().__init__(auth_manager)
        self.refresh_token()

    def get_balance(self):
        """[미국] 잔고 조회 (매수가능금액조회 API - TSLA 기준)"""
        
        # 1. 현금(구매력) 조회 - 매수가능금액조회 (VTTS3007R)
        cash = 0.0
        try:
            path = "/uapi/overseas-stock/v1/trading/inquire-psamount"
            tr_id = "VTTS3007R" if Config.MODE == 'PAPER' else "TTTS3007R"
            
            headers = {
                "authorization": f"Bearer {self.token}",
                "appkey": Config.APP_KEY, "appsecret": Config.APP_SECRET, "tr_id": tr_id
            }
            
            # [핵심] 테슬라(TSLA) 시장가(0) 기준으로 조회
            # AAPL 대신 TSLA를 쓰는 이유: 모의투자 서버 데이터 안정성
            params = {
                "CANO": Config.ACCOUNT_NO[:8],
                "ACNT_PRDT_CD": Config.ACCOUNT_NO[8:] if len(Config.ACCOUNT_NO) >= 10 else "01",
                "OVRS_EXCG_CD": "NAS",  # 나스닥
                "OVRS_ORD_UNPR": "0",   # 0을 넣으면 시장가 기준 계산
                "ITEM_CD": "TSLA"       # 테슬라
            }
            
            res = requests.get(f"{Config.URL_BASE}{path}", headers=headers, params=params)
            data = res.json()
            
            if data['rt_cd'] == '0' and 'output' in data:
                # ovrs_ord_psbl_amt: 해외주문가능금액 (원화 환산분 포함 가능성 있음)
                cash = float(data['output'].get('ovrs_ord_psbl_amt', 0))
                # print(f"💰 [Buying Power] 구매 가능 금액: ${cash:,.2f}")
            else:
                # 실패 시 로그 출력하되, 멈추지 않고 0으로 진행
                print(f"⚠️ [Cash] 구매력 조회 실패: {data.get('msg1')} (Code: {data.get('msg_cd')})")

        except Exception as e:
            print(f"⚠️ [Cash] 로직 에러: {e}")

        
        # 2. 보유 주식 조회 (기존 API: VTTS3012R) - 이건 잘 작동했음
        total_asset = cash
        holdings = {}
        
        try:
            path_stock = "/uapi/overseas-stock/v1/trading/inquire-balance"
            tr_id_stock = "VTTS3012R" if Config.MODE == 'PAPER' else "TTTS3012R"
            
            headers_stock = {
                "authorization": f"Bearer {self.token}",
                "appkey": Config.APP_KEY, "appsecret": Config.APP_SECRET, "tr_id": tr_id_stock
            }
            
            params_stock = {
                "CANO": Config.ACCOUNT_NO[:8],
                "ACNT_PRDT_CD": Config.ACCOUNT_NO[8:] if len(Config.ACCOUNT_NO) >= 10 else "01",
                "OVRS_EXCG_CD": "NAS", "TR_CRCY_CD": "USD",
                "CTX_AREA_FK100": "", "CTX_AREA_NK100": "",
                "CTX_AREA_FK200": "", "CTX_AREA_NK200": ""
            }

            res = requests.get(f"{Config.URL_BASE}{path_stock}", headers=headers_stock, params=params_stock)
            
            if res.status_code == 200:
                data = res.json()
                if 'output2' in data:
                    stock_val = float(data['output2'].get('tot_evlu_pfls_amt', 0))
                    total_asset = cash + stock_val

                if 'output1' in data:
                    for item in data['output1']:
                        qty = int(float(item['ovrs_cblc_qty']))
                        if qty > 0:
                            holdings[item['ovrs_pdno']] = qty
                            
        except Exception as e:
            print(f"⚠️ [Stock] 로직 에러: {e}")

        return total_asset, cash, holdings
    
    def get_balance_1(self):
        """[미국] 잔고 조회 (모의투자/실전 호환 개선)"""
        path = "/uapi/overseas-stock/v1/trading/inquire-balance"
        tr_id = "VTTS3012R" if Config.MODE == 'PAPER' else "TTTS3012R"
        
        headers = {
            "authorization": f"Bearer {self.token}",
            "appkey": Config.APP_KEY, 
            "appsecret": Config.APP_SECRET, 
            "tr_id": tr_id
        }
        params = {
            "CANO": Config.ACCOUNT_NO, 
            "ACNT_PRDT_CD": "01", 
            "OVRS_EXCG_CD": "NASD", 
            "TR_CRCY_CD": "USD", 
            "CTX_AREA_FK100": "", 
            "CTX_AREA_NK100": ""
        }
        
        try:
            res = requests.get(f"{Config.URL_BASE}{path}", headers=headers, params=params)
            if res.status_code == 200:
                data = res.json()
                if 'output2' in data:
                    # 🔍 디버깅: API가 주는 잔고 필드를 눈으로 확인하기 위해 출력
                    # (나중에 잘 되면 주석 처리하세요)
                    # print(f"🔍 [DEBUG] 미국 잔고 데이터: {data['output2']}")

                    # 외화 평가 금액 (내 주식의 가치)
                    total = float(data['output2']['tot_evlu_pfls_amt'])
                    
                    # [핵심 수정] 현금(예수금) 가져오기
                    # 모의투자는 'ovrs_ord_psbl_amt'(주문가능금액)을 써야 정확합니다.
                    cash = float(data['output2']['ovrs_ord_psbl_amt'])
                    
                    # 만약 위 필드도 0이라면 예비로 다른 필드 확인 (안전장치)
                    if cash == 0:
                        cash = float(data['output2'].get('frcr_ord_psbl_amt', 0))
                    
                    holdings = {}
                    if 'output1' in data:
                        for item in data['output1']:
                            qty = int(float(item['ovrs_cblc_qty']))
                            if qty > 0:
                                holdings[item['ovrs_pdno']] = qty
                    return total, cash, holdings
                else:
                    print("⚠️ [US] 잔고 조회 실패 (output2 없음)")
            else:
                print(f"⚠️ [US] API 오류: {res.json()}")
        except Exception as e:
            print(f"⚠️ [US] 잔고 조회 예외 발생: {e}")
            
        return 0.0, 0.0, {}
    
    def get_daily_data(self, code, exchange="NAS"):
        """[미국] 일봉 데이터"""
        path = "/uapi/overseas-price/v1/quotations/dailyprice"
        headers = {
            "authorization": f"Bearer {self.token}",
            "appkey": Config.APP_KEY, "appsecret": Config.APP_SECRET, "tr_id": "HHDFS76240000"
        }
        params = {
            "AUTH": "", "EXCD": exchange, "SYMB": code, "GUBN": "0", "BYMD": "", "MODP": "1"
        }
        res = requests.get(f"{Config.URL_BASE}{path}", headers=headers, params=params)
        if res.status_code == 200:
            output = res.json().get('output2', [])
            if output:
                return [{
                    "Date": r['xymd'], "Close": float(r['clos']),
                    "Open": float(r['open']), "High": float(r['high']),
                    "Low": float(r['low'])
                } for r in output]
        return []

    def send_order(self, code, side, price, qty, exchange="NAS"):
        """[미국] 주문"""
        path = "/uapi/overseas-stock/v1/trading/order"
        # 모의/실전 TR_ID 구분
        tr_id = ("VTTT1002U" if side == 'BUY' else "VTTT1006U") if Config.MODE == 'PAPER' else ("TTTT1002U" if side == 'BUY' else "TTTT1006U")
        
        # [변경 핵심] 가격 보정 (즉시 체결을 위해)
        # 매수할 땐 1% 비싸게, 매도할 땐 1% 싸게 주문을 던져서 우선순위를 높임
        # (실제 체결은 시장 현재가로 됨)
        adjusted_price = price
        if side == 'BUY':
            adjusted_price = price * 1.01 
        else:
            adjusted_price = price * 0.99
            
        # 소수점 2자리까지만 유효 (달러)
        final_price = f"{adjusted_price:.2f}"

        data = {
            "CANO": Config.ACCOUNT_NO, 
            "ACNT_PRDT_CD": "01",
            "OVRS_EXCG_CD": exchange, 
            "PDNO": code,
            "ORD_QTY": str(qty), 
            "OVRS_ORD_UNPR": final_price,
            "ORD_SVR_DVSN_CD": "0", 
            "ORD_DVSN": "00"
        }
        headers = {
            "authorization": f"Bearer {self.token}", 
            "appkey": Config.APP_KEY, 
            "appsecret": Config.APP_SECRET,
            "tr_id": tr_id, 
            "hashkey": self.auth_manager.get_hashkey(data)
        }
        res = requests.post(f"{Config.URL_BASE}{path}", headers=headers, data=json.dumps(data))
        if res.status_code == 200 and res.json()['rt_cd'] == '0':
            return True
        else:
            print(f"❌ 주문 실패: {res.json()}")
            return False

    def run(self):
        """미국장 통합 매매 로직 (Cleanup + Portfolio)"""
        self.refresh_token()
        total_asset, total_cash, holdings = self.get_balance()
        targets = load_target_stocks("US")

        # ---------------------------------------------------------
        # 🧹 [Cleanup] 미관리 종목 정리
        # ---------------------------------------------------------
        target_codes = set([t['code'] for t in targets])
        for held_code, qty in holdings.items():
            if held_code not in target_codes:
                # 미국장은 정리 시 거래소 정보가 필요한데, 일단 NAS로 가정하고 시도
                # (정확히 하려면 잔고 조회 시 거래소 정보도 저장해야 함)
                print(f"🧹 [Cleanup] 미관리 종목(US) 정리: {held_code} ({qty}주)")
                
                # 현재가 조회
                raw_data = self.get_daily_data(held_code) 
                if raw_data:
                    curr_p = float(raw_data[0]['Close'])
                    self.send_order(held_code, 'SELL', curr_p, qty)
                    total_cash += (qty * curr_p)
                time.sleep(0.2)

        # ---------------------------------------------------------
        # 🛡️ [Validation] 비율 검증
        # ---------------------------------------------------------
        min_cash_ratio = Config.MIN_CASH_RATIO
        total_stock_ratio = sum(t.get('target_ratio', 0) for t in targets)
        
        if (min_cash_ratio + total_stock_ratio) > 1.02:
            print(f"🚨 [US] 목표 비중 합계 초과! ({min_cash_ratio + total_stock_ratio:.2f})")

        min_cash_needed = total_asset * min_cash_ratio
        investable_cash = total_cash - min_cash_needed
        if investable_cash < 0: investable_cash = 0

        print(f"\n🇺🇸 [US] 자산: ${total_asset:,.2f} (투자 가용금: ${investable_cash:,.2f})")

        # ---------------------------------------------------------
        # 🚀 [Main Loop] 매매 수행
        # ---------------------------------------------------------
        for t in targets:
            code = t['code']
            name = t['name']
            exchange = t.get('exchange', 'NAS') # 거래소(NAS/NYS/AMS)
            target_ratio = t.get('target_ratio', 0)
            target_amt = total_asset * target_ratio

            # 데이터 조회
            raw_data = self.get_daily_data(code, exchange)
            if not raw_data: continue
            
            df = self.calculate_indicators(raw_data)
            if len(df) < 2: continue

            curr, prev = df.iloc[-1], df.iloc[-2]
            current_price = float(curr['Close']) # 미국장은 소수점 가격 존재
            
            # 전략 신호
            strategy_name = t.get('strategy', 'VOLATILITY_BREAKOUT') # 미국장 기본전략 추천
            setting = t.get('setting', {})
            signal, reason, _ = get_signal(strategy_name, curr, prev, setting)
            
            qty_held = holdings.get(code, 0)
            current_amt = qty_held * current_price

            # [A] 리밸런싱 매도
            if qty_held > 0 and current_amt > (target_amt * 1.2):
                excess_amt = current_amt - target_amt
                sell_qty = int(excess_amt // current_price)
                if sell_qty > 0:
                    print(f"   ⚖️ [{name}] 비중 초과 리밸런싱: {sell_qty}주 매도")
                    self.send_order(code, 'SELL', current_price, sell_qty, exchange)
                    investable_cash += (sell_qty * current_price)
                    total_cash += (sell_qty * current_price)

            # [B] 매수
            if signal == 'buy':
                needed_amt = target_amt - current_amt
                
                if needed_amt >= current_price:
                    if investable_cash < current_price:
                        print(f"   🔒 [{name}] 현금 비중 보호로 매수 스킵")
                        continue
                    
                    if needed_amt > investable_cash:
                        needed_amt = investable_cash
                    
                    buy_qty = int(needed_amt // current_price)
                    if buy_qty > 0:
                        print(f"   🚀 [{name}] 매수: {buy_qty}주 (목표비중 {target_ratio*100}%)")
                        self.send_order(code, 'BUY', current_price, buy_qty, exchange)
                        investable_cash -= (buy_qty * current_price)
                        total_cash -= (buy_qty * current_price)

            # [C] 매도
            elif signal == 'sell':
                if qty_held > 0:
                    print(f"   💧 [{name}] 신호 매도: {qty_held}주 ({reason})")
                    self.send_order(code, 'SELL', current_price, qty_held, exchange)
                    investable_cash += (qty_held * current_price)
                    total_cash += (qty_held * current_price)
            
            time.sleep(0.2)



