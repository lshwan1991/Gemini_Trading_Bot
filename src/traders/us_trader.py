import requests
import os
import json
import time
from datetime import datetime
from config import Config
from src.traders.base_trader import BaseTrader
from src.data_manager import load_target_stocks
from src.strategy import get_signal
from src.telegram_bot import send_telegram_msg
import csv

class USTrader(BaseTrader):
    def __init__(self, auth_manager):
        super().__init__(auth_manager)
        self.last_report_time = 0
        
        # ✅ [핵심] 주문 관리 큐 (미체결 주문 목록)
        # 구조: [{'odno': '주문번호', 'code': 'AAPL', 'time': 시간, 'type': 'BUY', 'amt': 금액}]
        self.pending_orders = [] 

    def get_balance(self):
        """[미국] 잔고 조회 (나스닥 기준)"""
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
            "OVRS_EXCG_CD": "NASD", # NASD (나스닥) 기준 조회
            "TR_CRCY_CD": "USD",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": ""
        }

        try:
            res = requests.get(f"{Config.URL_BASE}{path}", headers=headers, params=params)
            data = res.json()
            
            if data['rt_cd'] == '0':
                out2 = data['output2']
                # frcr_dncl_amt_2: 외화예수금 (실전에서는 확인 필요, 보통 이것 사용)
                total_cash = float(out2.get('frcr_dncl_amt_2', 0)) 

                holdings = {}
                details = {}
                
                for item in data['output1']:
                    qty = int(float(item['ovrs_cblc_qty']))
                    if qty > 0:
                        code = item['ovrs_pdno']
                        name = item['ovrs_item_name']
                        curr_price = float(item['now_pric2'])
                        eval_amt = float(item['frcr_evlu_amt2'])
                        
                        holdings[code] = qty
                        details[code] = {
                            "name": name,
                            "qty": qty,
                            "curr_price": curr_price,
                            "eval_amt": eval_amt
                        }
                
                # 총 자산 = 현금 + 주식평가액
                total_stock_val = sum(d['eval_amt'] for d in details.values())
                total_asset = total_cash + total_stock_val
                
                return total_asset, total_cash, holdings, details
            else:
                return 0.0, 0.0, {}, {}
        except Exception as e:
            print(f"⚠️ [US] 잔고 조회 에러: {e}")
            return 0.0, 0.0, {}, {}

    def get_daily_data(self, code):
        """[미국] 일봉 데이터 (나스닥 기준)"""
        path = "/uapi/overseas-price/v1/quotations/dailyprice"
        headers = {
            "authorization": f"Bearer {self.token}",
            "appkey": Config.APP_KEY,
            "appsecret": Config.APP_SECRET,
            "tr_id": "HHDFS76240000"
        }
        params = {
            "AUTH": "",
            "EXCD": "NAS", # 기본 NAS (필요시 NYS, AMS 등으로 확장 가능)
            "SYMB": code,
            "GUBN": "0",
            "BYMD": "",
            "MODP": "1"
        }
        
        try:
            res = requests.get(f"{Config.URL_BASE}{path}", headers=headers, params=params)
            if res.status_code == 200 and res.json()['rt_cd'] == '0':
                items = res.json().get('output2', [])
                return [{
                    "Date": item['xymd'],
                    "Close": float(item['clos']),
                    "Open": float(item['open']),
                    "High": float(item['high']),
                    "Low": float(item['low']),
                    "Volume": int(float(item['tvol']))
                } for item in items]
            return []
        except:
            return []

    def send_order(self, code, side, price, qty):
        """[미국] 지정가 주문 전송"""
        path = "/uapi/overseas-stock/v1/trading/order"
        # 모의/실전 TR_ID 구분
        if Config.MODE == 'PAPER':
            tr_id = "VTTT1002U" if side == 'BUY' else "VTTT1001U"
        else:
            tr_id = "TTTS1002U" if side == 'BUY' else "TTTS1001U"

        data = {
            "CANO": Config.ACCOUNT_NO,
            "ACNT_PRDT_CD": "01",
            "OVRS_EXCG_CD": "NASD", 
            "PDNO": code,
            "ORD_QTY": str(qty),
            "OVRS_ORD_UNPR": str(price),
            "ORD_SVR_DVSN_CD": "0",
            "ORD_DVSN": "00" # 00: 지정가 (Limit)
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
            odno = res.json()['output']['ODNO']
            print(f"   📝 [주문 접수] {side} {code} {qty}주 (주문번호: {odno})")
            return odno
        else:
            print(f"❌ [US] 주문 실패: {res.json()['msg1']}")
            return None

    def get_unfilled_orders(self):
        """✅ [미국] 미체결 내역 조회 (요청하신 함수)"""
        path = "/uapi/overseas-stock/v1/trading/inquire-nccs"
        tr_id = "VTTS3018R" if Config.MODE == 'PAPER' else "TTTS3018R"
        
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
            "SORT_SQN": "DS",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": ""
        }
        
        try:
            res = requests.get(f"{Config.URL_BASE}{path}", headers=headers, params=params)
            unfilled_list = []
            
            if res.json()['rt_cd'] == '0':
                for item in res.json().get('output', []):
                    # 주문수량 - 체결수량 = 잔량 (0보다 크면 미체결)
                    remain = int(item['ord_qty']) - int(item['ccld_qty'])
                    if remain > 0:
                        unfilled_list.append({
                            "odno": item['odno'],
                            "code": item['pdno'],
                            "qty": remain,
                            "price": item['ord_unpr']
                        })
            return unfilled_list
        except Exception as e:
            print(f"⚠️ [US] 미체결 조회 에러: {e}")
            return []

    def cancel_order(self, odno, code):
        """✅ [미국] 주문 취소 (요청하신 함수)"""
        path = "/uapi/overseas-stock/v1/trading/order-rvsecncl"
        # 모의/실전 TR_ID 구분 (취소는 VTTT1004U / TTTS1004U)
        tr_id = "VTTT1004U" if Config.MODE == 'PAPER' else "TTTS1004U"
        
        data = {
            "CANO": Config.ACCOUNT_NO,
            "ACNT_PRDT_CD": "01",
            "OVRS_EXCG_CD": "NASD", 
            "PDNO": code,
            "ORGN_ODNO": odno, # 취소할 원주문번호
            "ORD_QTY": "0",    # 0 입력 시 전량 취소
            "RVSE_CNCL_DVSN_CD": "02", # 02: 취소
            "ORD_SVR_DVSN_CD": "0",
            "OVRS_ORD_UNPR": "0" 
        }
        
        headers = {
            "authorization": f"Bearer {self.token}",
            "appkey": Config.APP_KEY,
            "appsecret": Config.APP_SECRET,
            "tr_id": tr_id,
            "hashkey": self.auth_manager.get_hashkey(data)
        }
        
        try:
            res = requests.post(f"{Config.URL_BASE}{path}", headers=headers, data=json.dumps(data))
            if res.json()['rt_cd'] == '0':
                print(f"   🗑️ 주문 취소 완료 (번호: {odno})")
                return True
            else:
                print(f"❌ 취소 실패: {res.json()['msg1']}")
                return False
        except Exception as e:
            print(f"⚠️ 취소 에러: {e}")
            return False

    def check_pending_orders(self):
        """📋 [관리] 대기열(Queue)에 있는 주문 상태 점검 (Non-blocking)"""
        if not self.pending_orders: return

        # 미체결 내역 API 조회
        unfilled_list = self.get_unfilled_orders() 
        
        # 역순 순회 (삭제 안전하게)
        for i in range(len(self.pending_orders) - 1, -1, -1):
            order = self.pending_orders[i]
            elapsed_time = time.time() - order['time']
            
            # 내 주문번호가 미체결 리스트에 있는가?
            is_unfilled = any(u['odno'] == order['odno'] for u in unfilled_list)
            
            if not is_unfilled:
                # 없으면 -> 체결 완료! 🎉
                send_telegram_msg(f"🇺🇸 [{order['type']} 체결] {order['name']} (주문번호: {order['odno']})")
                self.pending_orders.pop(i) 
                continue
            
            # 60초 초과 시 취소
            if elapsed_time > 60:
                print(f"   ⏳ [Time Out] {order['name']} 60초 경과 -> 취소 시도")
                if self.cancel_order(order['odno'], order['code']):
                    send_telegram_msg(f"🇺🇸 [취소] {order['name']} 미체결 취소")
                self.pending_orders.pop(i)

    def run(self):
        """메인 실행 로직 (Non-blocking + Cleanup + Validation)"""
        self.refresh_token()
        
        # 1. 자산 및 타겟 로드
        total_asset, total_cash, holdings, details = self.get_balance()
        targets = load_target_stocks("US")
        
        if not targets: return

        # ---------------------------------------------------------
        # 🔄 0. 대기 주문(Queue) 관리
        # ---------------------------------------------------------
        self.check_pending_orders()

        # ---------------------------------------------------------
        # 🧹 1. [Cleanup] 미관리 종목 정리 (요청하신 로직 추가)
        # ---------------------------------------------------------
        target_codes = set([t['code'] for t in targets])
        for held_code, qty in holdings.items():
            if held_code not in target_codes:
                # 미국장은 정리 시 거래소 정보가 필요하지만, 일단 NAS로 가정하고 시도
                print(f"🧹 [Cleanup] 미관리 종목(US) 정리: {held_code} ({qty}주)")
                
                raw_data = self.get_daily_data(held_code) 
                if raw_data:
                    curr_p = float(raw_data[0]['Close']) # 현재가 근사치
                    # 매도 주문 전송 (시장가가 없으므로 현재가 지정가로)
                    odno = self.send_order(held_code, 'SELL', curr_p, qty)
                    
                    if odno:
                        # 매도도 큐에 등록해서 체결 관리
                        self.pending_orders.append({
                            'odno': odno, 'code': held_code, 'name': held_code,
                            'type': 'SELL', 'qty': qty, 'price': curr_p, 'amt': 0, 'time': time.time()
                        })
                time.sleep(0.2)

        # ---------------------------------------------------------
        # 🛡️ 2. [Validation] 비율 검증 (요청하신 로직 추가)
        # ---------------------------------------------------------
        # 주의: Config.MIN_CASH_RATIO가 config.py에 정의되어 있어야 합니다.
        min_cash_ratio = getattr(Config, 'MIN_CASH_RATIO', 0.05) # 없으면 기본 5%
        total_stock_ratio = sum(t.get('target_ratio', 0) for t in targets)
        
        if (min_cash_ratio + total_stock_ratio) > 1.02:
            print(f"🚨 [US] 목표 비중 합계 초과! ({min_cash_ratio + total_stock_ratio:.2f})")

        # 투자 가능 금액 계산 (Queue에 잠긴 금액 제외)
        locked_cash = 0
        for order in self.pending_orders:
            if order['type'] == 'BUY':
                locked_cash += order['amt']

        min_cash_needed = total_asset * min_cash_ratio
        investable_cash = total_cash - locked_cash - min_cash_needed
        if investable_cash < 0: investable_cash = 0

        print(f"\n🇺🇸 [US] 자산: ${total_asset:,.2f} | 현금: ${total_cash:,.2f} (가용: ${investable_cash:,.2f})")

        # -----------------------------------------------------------
        # 🚀 3. 매매 루프 (Non-blocking)
        # -----------------------------------------------------------
        for t in targets:
            code = t['code']
            name = t['name']
            
            # 이미 대기열에 주문이 있는 종목은 Skip
            if any(p['code'] == code for p in self.pending_orders):
                print(f"   🔒 [{name}] 주문 처리 중... (Skip)")
                continue

            # 데이터 조회
            raw_data = self.get_daily_data(code)
            if not raw_data: continue
            
            df = self.calculate_indicators(raw_data)
            if df.empty: continue
            
            curr = df.iloc[-1]
            prev = df.iloc[-2]
            current_price = float(curr['Close'])
            
            signal, reason, _ = get_signal(t.get('strategy'), curr, prev, t.get('setting'))
            qty_held = holdings.get(code, 0)
            
            # [매수 로직]
            if signal == 'buy':
                target_amt = total_asset * t.get('target_ratio', 0)
                current_amt = qty_held * current_price
                needed_amt = target_amt - current_amt
                
                # 가용 현금 체크
                if needed_amt >= current_price and investable_cash >= current_price:
                    if needed_amt > investable_cash: needed_amt = investable_cash
                    
                    buy_qty = int(needed_amt // current_price)
                    if buy_qty > 0:
                        print(f"   🚀 [{name}] 매수 주문: {buy_qty}주 (@ ${current_price})")
                        odno = self.send_order(code, 'BUY', current_price, buy_qty)
                        
                        if odno:
                            # 큐에 등록 (현금 잠금)
                            self.pending_orders.append({
                                'odno': odno, 'code': code, 'name': name,
                                'type': 'BUY', 'qty': buy_qty, 'price': current_price,
                                'amt': buy_qty * current_price, 'time': time.time()
                            })
                            investable_cash -= (buy_qty * current_price)

            # [매도 로직]
            elif signal == 'sell' and qty_held > 0:
                print(f"   💧 [{name}] 매도 주문: {qty_held}주")
                odno = self.send_order(code, 'SELL', current_price, qty_held)
                
                if odno:
                    # 큐에 등록
                    self.pending_orders.append({
                        'odno': odno, 'code': code, 'name': name,
                        'type': 'SELL', 'qty': qty_held, 'price': current_price,
                        'amt': 0, 'time': time.time()
                    })

            time.sleep(0.2)