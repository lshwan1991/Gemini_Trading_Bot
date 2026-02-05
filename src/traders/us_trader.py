import requests
import os
import json
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed # ✅ 병렬 처리 필수 모듈

from config import Config
from src.traders.base_trader import BaseTrader
from src.data_manager import load_target_stocks
from src.strategy import get_signal
from src.telegram_bot import send_telegram_msg
import csv

class USTrader(BaseTrader):
    def __init__(self, auth_manager):
        super().__init__(auth_manager)
        self.pending_orders = [] 
    
    def check_is_market_open(self):
        """
        [미국장 영업 시간 체크]
        - 정규장: 23:30 ~ 06:00 (한국시간, 서머타임 해제 기준)
        - 서머타임 적용 시: 22:30 ~ 05:00
        - 주말(토/일) 제외
        """
        now = datetime.now()
        weekday = now.weekday() # 0:월 ~ 6:일
        current_time = int(now.strftime("%H%M")) # 예: 2330, 0500

        # 1. 주말 체크 (토요일 아침 6시 이후 ~ 월요일 밤 11시 반 전까지 쉼)
        # 토요일(5) 07:00 이후 ~ 월요일(0) 22:00 이전에는 무조건 휴장으로 처리
        if weekday == 5 and current_time > 700: return False # 토요일 아침 이후
        if weekday == 6: return False # 일요일 하루 종일
        if weekday == 0 and current_time < 2200: return False # 월요일 장 시작 전

        # 2. 시간 체크 (단순화: 22:00 ~ 06:30 사이만 "Open"으로 간주)
        # (프리마켓 포함 넉넉하게 잡되, 낮 시간대 오작동 방지)
        if 2200 <= current_time or current_time <= 630:
            return True
            
        print(f"   💤 [Sleep] 미국장 운영 시간이 아닙니다. ({current_time})")
        return False

    # ==================================================================
    # [Core] 자산 및 현재가 조회
    # =================================================================
    def get_balance(self):
        """
        [통합 잔고 조회]
        - 현금(예수금)과 보유 주식을 한 번에 정확하게 조회합니다.
        - 이전 코드의 '보유 주식 누락' 문제를 해결합니다.
        """
        print("\n🔍 [System] 자산 현황 갱신 중 (통합 잔고 API)...")

        # API 엔드포인트: 해외주식 체결기준현재잔고
        path = "/uapi/overseas-stock/v1/trading/inquire-present-balance"
        
        # TR ID 설정 (실전: CTRP6504R / 모의: VTRP6504R)
        if self.mode == 'PAPER':
            tr_id = "VTRP6504R"
        else:
            tr_id = "CTRP6504R" # ✅ 실전투자 필수 ID

        headers = {
            "authorization": f"Bearer {self.token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id
        }

        # 나스닥(NAS) 기준으로 조회하면 뉴욕/아멕스 종목도 다 나옵니다.
        params = {
            "CANO": self.account_no,
            "ACNT_PRDT_CD": "01",
            "WCRC_FRCR_DVSN_CD": "02", 
            "NATN_CD": "840",     # 미국
            "TR_MKET_CD": "00",
            "INQR_DVSN_CD": "01"
        }

        try:
            res = self.session.get(f"{self.url_base}{path}", headers=headers, params=params, timeout=5)
            data = res.json()

            if data['rt_cd'] != '0':
                print(f"❌ [Balance] 조회 실패: {data.get('msg1')}")
                return 0.0, 0.0, {}, {}

            out1 = data.get('output1', []) # 보유 종목 리스트
            out2 = data.get('output2', []) # 계좌 자산 현황

            # 헬퍼 함수: 빈 문자열 안전 변환
            def safe_float(val):
                if not val or val.strip() == "": return 0.0
                return float(val)

            # 1. 현금 계산 (실시간 보정)
            current_usd = 0.0
            deposit = 0.0
            today_buy = 0.0

            # 1. 현금 (해외주문가능금액)
            if out2:
                # 예수금 (아직 매수 대금이 안 빠져나간 장부상 금액)
                deposit = safe_float(out2[0].get('frcr_dncl_amt_2', 0))
                # 당일 매매 내역 (매수/매도)
                today_buy = safe_float(out2[0].get('frcr_buy_amt_smtl', 0)) # 오늘 산 돈
                today_sell = safe_float(out2[0].get('frcr_sll_amt_smtl', 0)) # 오늘 판 돈
                # ✅ [핵심] 가용 현금 = 예수금 - 산 돈 + 판 돈
                current_usd = deposit - today_buy + today_sell
            
            # 2. 보유 주식 파싱
            holdings = {}
            details = {}
            total_stock_eval = 0.0

            for item in out1:
                # ccld_qty_smtl1: 체결 수량 (가장 정확)
                qty = int(safe_float(item['ccld_qty_smtl1']))
                
                if qty > 0:
                    code = item['pdno'] # 종목 코드
                    name = item['prdt_name']
                    curr_price = safe_float(item['ovrs_now_pric1'])    # 현재가
                    avg_price = safe_float(item['avg_unpr3']) # 평단가
                    eval_amt = safe_float(item['frcr_evlu_amt2']) # 평가금액($)
                    profit_rate = safe_float(item['evlu_pfls_rt1'])    # 수익률(%)

                    holdings[code] = qty
                    details[code] = {
                        "name": name,
                        "qty": qty,
                        "curr_price": curr_price,
                        "avg_price": avg_price,
                        "eval_amt": eval_amt,
                        "profit_rate": profit_rate,
                        "exchange": "NASD" # 기본값
                    }
                    total_stock_eval += eval_amt
            
            # 총 자산 = (보정된 현금) + 주식 평가금액
            total_asset = current_usd + total_stock_eval
            
            # 현금 비중 로그
            print(f"   💰 [Total Asset] 총 자산: ${total_asset:,.2f}")
            print(f"      (현금: ${current_usd:,.2f} = 예수금 ${deposit:,.2f} - 매수 ${today_buy:,.2f})")
            
            if holdings:
                print(f"   📂 [Holdings] 보유 종목: {list(holdings.keys())}")

            return total_asset, current_usd, holdings, details

        except Exception as e:
            print(f"⚠️ [Balance] 에러 발생: {e}")
            return 0.0, 0.0, {}, {}

    def get_current_price(self, code, exchange="NASD"):
        """[미국] 실시간 현재가 조회"""
        lookup_exch = "NAS"
        ex_upper = exchange.upper()
        if ex_upper in ["NYSE", "NYS", "NEWYORK"]: lookup_exch = "NYS"
        elif ex_upper in ["AMEX", "AMS"]: lookup_exch = "AMS"

        path = "/uapi/overseas-price/v1/quotations/price"
        headers = {
            "authorization": f"Bearer {self.token}",
            "appkey": self.app_key, 
            "appsecret": self.app_secret,
            "tr_id": "HHDFS00000300"
        }
        params = {"AUTH": "", "EXCD": lookup_exch, "SYMB": code}
        
        try:
            res = self.session.get(f"{self.url_base}{path}", headers=headers, params=params, timeout=2)
            if res.status_code == 200:
                data = res.json()
                if data['rt_cd'] == '0':
                    return float(data['output']['last'])
                elif "만료" in data['msg1']:
                    self.force_refresh_token()
            return None
        except Exception as e:
            return None

        except Exception as e:
            # 세션이 재시도했음에도 실패한 경우
            print(f"⚠️ [Price Error] {code}: {e}")
            return None
    
    def force_refresh_token(self):
        """🚨 토큰 강제 갱신 헬퍼 함수"""
        file_name = f"data/token_{self.mode.lower()}.json"
        if os.path.exists(file_name):
            os.remove(file_name)
        self.refresh_token()

    def get_daily_data(self, code, exchange="NASD"):
        """[미국] 일봉 데이터 조회 (세션 & 타임아웃 적용)"""
        lookup_exch = "NAS"
        ex_upper = exchange.upper()
        if ex_upper in ["NYSE", "NYS"]: lookup_exch = "NYS"
        elif ex_upper in ["AMEX", "AMS"]: lookup_exch = "AMS"

        path = "/uapi/overseas-price/v1/quotations/dailyprice"
        headers = {
            "authorization": f"Bearer {self.token}", 
            "appkey": self.app_key, 
            "appsecret": self.app_secret,
            "tr_id": "HHDFS76240000"
        }
        params = {
            "AUTH": "", 
            "EXCD": lookup_exch, 
            "SYMB": code, 
            "GUBN": "0", 
            "BYMD": "", 
            "MODP": "1"
        }
        
        try:
            res = self.session.get(f"{self.url_base}{path}", headers=headers, params=params, timeout=2)
            if res.status_code == 200 and res.json()['rt_cd'] == '0':
                items = res.json().get('output2', [])
                if items:
                    return [{
                        "Date": item['xymd'], "Close": float(item['clos']),
                        "Open": float(item['open']), "High": float(item['high']),
                        "Low": float(item['low']), "Volume": int(float(item['tvol']))
                    } for item in items]
            return []
        except Exception as e:
            return []
        
    # ==================================================================
    # [Order] 주문 실행
    # ==================================================================
    def send_order(self, code, side, price, qty, exchange="NASD"):
        """[미국] 주문 전송 (지정가 0.5% 보정 + 거래소 코드 자동 변환)"""
        # 1. 거래소 코드 변환
        target_exch = "NASD" # 기본값
        ex_upper = exchange.upper()
        if ex_upper in ["NYSE", "NYS", "NEWYORK"]: target_exch = "NYSE"
        elif ex_upper in ["AMEX", "AMS"]: target_exch = "AMEX"
        else: target_exch = "NASD"

        # 가격 보정 (즉시 체결 유도)
        if side == 'BUY': limit_price = round(price * 1.005, 2)
        else: limit_price = round(price * 0.995, 2)

        formatted_price = f"{limit_price:.2f}"
        print(f"   📡 [Sending] {side} {code} {qty}주 @ ${formatted_price} (지정가/0.5%보정) (Exch: {target_exch})")

        path = "/uapi/overseas-stock/v1/trading/order"

        if self.mode == 'PAPER':
            # 모의투자
            tr_id = "VTTT1002U" if side == 'BUY' else "VTTT1001U"
        else:
            # 실전투자 (미국주식 전용 TR)
            tr_id = "TTTT1002U" if side == 'BUY' else "TTTT1006U"

        data = {
            "CANO": self.account_no,
            "ACNT_PRDT_CD": "01", 
            "OVRS_EXCG_CD": target_exch,
            "PDNO": code, 
            "ORD_QTY": str(qty), 
            "OVRS_ORD_UNPR": formatted_price,
            "ORD_SVR_DVSN_CD": "0", 
            "ORD_DVSN": "00" #00 지정가
        }
        
        headers = {
            "authorization": f"Bearer {self.token}", 
            "appkey": self.app_key, 
            "appsecret": self.app_secret,
            "tr_id": tr_id, 
            "hashkey": self.auth_manager.get_hashkey(data)
        }
        
        try:
            res = self.session.post(f"{self.url_base}{path}", headers=headers, data=json.dumps(data), timeout=5)
            if res.status_code == 200 and res.json()['rt_cd'] == '0':
                odno = res.json()['output']['ODNO']
                print(f"   ✅ [Accepted] 주문 접수 완료 (No: {odno})")
                return odno
            else:
                msg = res.json().get('msg1', '')
                if "휴장" in msg or "장운영" in msg or "Closed" in msg or "Holiday" in msg:
                     print(f"   😴 [Holiday] 미국장 휴장 감지! ({msg})")
                     return 'HOLIDAY'
                elif "만료" in msg:
                    self.force_refresh_token()
                else:
                    print(f"   ❌ [Failed] 주문 실패: {msg}")
                return None
        except Exception as e:
            print(f"   ⚠️ [API Error] {e}")
            return None

    def get_unfilled_orders(self):
        """[API] 미체결 내역 조회"""
        path = "/uapi/overseas-stock/v1/trading/inquire-nccs"
        tr_id = "VTTS3018R" if self.mode == 'PAPER' else "TTTS3018R" 
        
        headers = {
            "authorization": f"Bearer {self.token}", 
            "appkey": self.app_key, 
            "appsecret": self.app_secret, 
            "tr_id": tr_id
        }
        params = {
            "CANO": self.account_no, 
            "ACNT_PRDT_CD": "01", 
            "OVRS_EXCG_CD": "NASD",
            "SORT_SQN": "DS", 
            "CTX_AREA_FK100": "", 
            "CTX_AREA_NK100": ""
        }
        
        try:
            res = self.session.get(f"{self.url_base}{path}", headers=headers, params=params)
            res_json = res.json()
            unfilled_list = []
            
            if res_json['rt_cd'] == '0':
                for item in res_json.get('output', []):
                    # 잔량(ord_qty - ccld_qty)이 있는 것만
                    remain = int(item['ord_qty']) - int(item['ccld_qty'])
                    if remain > 0:
                        unfilled_list.append({
                            "odno": item['odno'], 
                            "code": item['pdno'], 
                            "qty": remain
                        })
            return unfilled_list
        except Exception as e:
            print(f"⚠️ [Unfilled Check Error] {e}")
            return []

    def cancel_order(self, odno, code):
        """주문 취소"""
        print(f"   🗑️ [Canceling] 주문 {odno} 취소 요청...")
        path = "/uapi/overseas-stock/v1/trading/order-rvsecncl"
        tr_id = "VTTT1004U" if self.mode == 'PAPER' else "TTTS1004U"
        data = {
            "CANO": self.account_no, "ACNT_PRDT_CD": "01", "OVRS_EXCG_CD": "NASD", 
            "PDNO": code, "ORGN_ODNO": odno, "ORD_QTY": "0", "RVSE_CNCL_DVSN_CD": "02",
            "ORD_SVR_DVSN_CD": "0", "OVRS_ORD_UNPR": "0" 
        }
        headers = {
            "authorization": f"Bearer {self.token}", "appkey": self.app_key, "appsecret": self.app_secret,
            "tr_id": tr_id, "hashkey": self.auth_manager.get_hashkey(data)
        }
        try:
            res = requests.post(f"{self.url_base}{path}", headers=headers, data=json.dumps(data))
            if res.json()['rt_cd'] == '0':
                print(f"   ✅ 취소 완료")
                return True
            return False
        except:
            return False

    def check_pending_orders(self):
        """대기열 관리 (체결 확인 및 타임아웃 취소)"""
        if not self.pending_orders: return
        # 1. 미체결 내역(API) 조회
        unfilled_list = self.get_unfilled_orders() 
        print(f"\n📋 [Queue] 주문 대기열 {len(self.pending_orders)}건 확인 중...")

        # 리스트를 역순으로 순회하며 삭제 (pop 안전하게)
        for i in range(len(self.pending_orders) - 1, -1, -1):
            order = self.pending_orders[i]
            # (A) 타임아웃 체크 (60초)
            if time.time() - order['time'] > 60:
                print(f"      ⏰ [Timeout] {order['code']} 60초 경과 -> 취소 실행")
                self.cancel_order(order['odno'], order['code']) # 취소 주문 전송
                send_telegram_msg(f"🗑️ [취소] {order['name']} 미체결 취소 (Timeout)")
                self.pending_orders.pop(i) # 대기열에서 삭제
                continue
            
            # (B) 체결 여부 확인
            # 미체결 리스트에 내 주문번호(odno)가 있는가?
            is_still_unfilled = False
            for u in unfilled_list:
                if str(u['odno']) == str(order['odno']): # 문자열 비교 안전하게
                    is_still_unfilled = True
                    break
            
            # 미체결 리스트에 없으면 -> "체결됨" (또는 이미 취소됨)
            if not is_still_unfilled:
                print(f"   🎉 [Filled] {order['name']} 주문 처리 완료 (체결/취소)")
                # 체결 알림 (취소가 아닐 경우에만.. 근데 구분 어려우니 일단 체결로 간주)
                send_telegram_msg(f"🇺🇸 [체결 확인] {order['name']} {order['type']} 완료")
                self.pending_orders.pop(i) # 대기열에서 삭제
            else:
                print(f"      ⏳ {order['name']} 아직 미체결 상태...")

    # ==================================================================
    # [Report] 포트폴리오 보고서
    # ==================================================================
    def report_targets(self):
        """장 시작 전 보고 (목표 비중 0% 제외)"""
        targets = load_target_stocks("US")
        if not targets: return "❌ [Error] 타겟 파일 로드 실패"
        
        total_ratio = sum(t.get('target_ratio', 0) for t in targets)
        msg = f"☀️ **[오늘의 목표 포트폴리오 (US)]**\n🎯 주식 비중: {total_ratio*100:.1f}%\n\n"
        
        # 🚨 [수정] 비중 0% 초과인 종목만 필터링
        valid_targets = [t for t in targets if t.get('target_ratio', 0) > 0]
        
        if valid_targets:
            for t in valid_targets:
                exch = t.get('exchange', 'NASD')
                msg += f"🔹 {t['name']} ({t['code']}): {t.get('target_ratio',0)*100:.1f}%\n"
        else:
            msg += "   (매수 목표 종목 없음)\n"
            
        return msg
    
    def report_balance(self):
        """🌙 [Report] 장 마감 결산 보고 (수익률 순 정렬)"""
        self.refresh_token()
        
        # 1. 자산 데이터 조회
        total_asset, total_usd, holdings, details = self.get_balance()
        
        # 2. 총 평가 손익 계산
        total_eval_profit = sum(d['eval_amt'] - (d['avg_price'] * d['qty']) for d in details.values())

        # 3. 헤더 작성
        msg = "🌙 **[장 마감 결산 보고 (US)]**\n"
        msg += f"💰 총 자산: ${total_asset:,.2f}\n"
        msg += f"💵 달러현금: ${total_usd:,.2f}\n"
        msg += "-" * 30 + "\n"
        msg += f"📈 총 평가손익: ${total_eval_profit:+,.2f}\n"
        msg += "-" * 30 + "\n"
        
        # 4. 종목별 상세
        if details:
            msg += "**[보유 종목 상세 (수익률 순)]**\n"
            
            # 리스트로 변환 및 정렬 준비
            holding_list = []
            for code, info in details.items():
                if info['qty'] > 0:
                    info['code'] = code
                    info['weight'] = (info['eval_amt'] / total_asset * 100) if total_asset > 0 else 0
                    info['profit_amt'] = info['eval_amt'] - (info['avg_price'] * info['qty'])
                    holding_list.append(info)
            
            # 🚨 [수정] 수익률 높은 순서대로 정렬 (내림차순)
            holding_list.sort(key=lambda x: x['profit_rate'], reverse=True)
            
            for info in holding_list:
                # 아이콘 (수익/손실)
                icon = "🔴" if info['profit_rate'] > 0 else "🔵"
                
                msg += f"{icon} **{info['name']}** ({info['code']})\n"
                msg += f"   • 수익: ${info['profit_amt']:+,.2f} ({info['profit_rate']:+.2f}%)\n"
                msg += f"   • 단가: ${info['avg_price']:,.2f} → ${info['curr_price']:,.2f}\n"
                msg += f"   • 비중: {info['weight']:.1f}% (${info['eval_amt']:,.2f})\n\n"
        else:
            msg += "💤 보유 주식 없음 (100% 현금)\n"
            
        return msg
    
    def report_portfolio_status(self):
        """📊 생존 신고 + [Report] 3시간 주기 리포트 (수익률 순 정렬)"""
        # 1. 자산 조회
        total_asset, total_usd, holdings, details = self.get_balance()
        
        # 2. 현금 비중 계산
        cash_ratio = (total_usd / total_asset * 100) if total_asset > 0 else 0
        
        # 3. 메시지 헤더
        msg = f"🇺🇸 **[Portfolio Status]**\n"
        msg += f"💰 자산: ${total_asset:,.2f} (현금 {cash_ratio:.1f}%)\n"
        msg += "-" * 30 + "\n"

        # 타겟 로드 & 매핑
        targets = load_target_stocks("US")
        target_map = {t['code']: t.get('target_ratio', 0) for t in targets}
        
        # 4. 보유 종목 리스팅 (정렬 적용)
        active_stocks = []
        if details:
            for code, info in details.items():
                # 수량 0 이하는 제외
                if info['qty'] <= 0: continue

                info['code'] = code
                info['target_ratio'] = target_map.get(code, 0)
                info['current_ratio'] = (info['eval_amt'] / total_asset) * 100
                active_stocks.append(info)

        # 🚨 [수정] 수익률 높은 순서대로 정렬
        active_stocks.sort(key=lambda x: x['profit_rate'], reverse=True)
        
        if active_stocks:
            for info in active_stocks:
                target_ratio_pct = info['target_ratio'] * 100
                
                # 아이콘
                icon = "🔴" if info['profit_rate'] > 0 else "🔵"
                if info['profit_rate'] == 0: icon = "⚪"
                
                msg += f"{icon} **{info['name']}** ({info['code']})\n"
                msg += f"   • 수익: {info['profit_rate']:+.2f}%  |  ${info['eval_amt']:,.2f}\n"
                msg += f"   • 단가: ${info['avg_price']:,.2f} → ${info['curr_price']:,.2f}\n"
                msg += f"   • 비중: {info['current_ratio']:.1f}% (목표 {target_ratio_pct:.0f}%)\n"
                msg += "-" * 30 + "\n"
        else:
            msg += "💤 현재 보유 중인 종목이 없습니다.\n"
        
        send_telegram_msg(msg)

    def print_portfolio_log(self, total_asset, details, targets):
        """📝 [Log] 포트폴리오 비중 콘솔 출력 (수익률 순 정렬)"""
        print("\n📊 [Portfolio Status]")
        
        # 출력할 리스트 만들기
        print_list = []
        
        # 보유 중인 종목만 추림 (details 기반)
        if details:
            for code, info in details.items():
                if info.get('qty', 0) > 0:
                    # 목표 비중 찾기
                    t_ratio = 0
                    for t in targets:
                        if t['code'] == code:
                            t_ratio = t.get('target_ratio', 0)
                            break
                    
                    info['name'] = info.get('name', code) # 이름 없으면 코드로
                    info['target_r_pct'] = t_ratio * 100
                    info['curr_r_pct'] = (info['eval_amt'] / total_asset * 100) if total_asset > 0 else 0
                    print_list.append(info)

        # 🚨 [수정] 수익률 순 정렬
        print_list.sort(key=lambda x: x.get('profit_rate', 0), reverse=True)

        if print_list:
            print(f"   {'종목명':<10} | {'수익률':^8} | {'평가금액($)':^12} | {'비중':^6}")
            print("-" * 55)
            for info in print_list:
                print(f"   {info['name']:<10} | {info['profit_rate']:>6.2f}% | {info['eval_amt']:>11,.2f} | {info['curr_r_pct']:>5.1f}% (목{info['target_r_pct']:.0f}%)")
        else:
            print("   보유 종목 없음")
            
        print("-" * 55)

    # ==================================================================
    # [Main Logic] 봇 실행
    # ==================================================================
    def run(self):

        if not self.check_is_market_open():
            return "MARKET_CLOSED"
       
        print("\n" + "="*50 + f"\n🚀 [USTrader] 사이클 시작 ({datetime.now().strftime('%H:%M:%S')})\n" + "="*50)
        self.refresh_token()
        
        # 1. 자산/타겟 로드
        total_asset, total_cash, holdings, details = self.get_balance()
        targets = load_target_stocks("US")
        if not targets: 
            print("🚨 [System] 타겟 종목 파일이 비어있거나 로드 실패.")
            return

        # 2. 미체결 주문 관리
        self.check_pending_orders()

        # ==================================================================
        # 🛑 [NEW] 과매수 방지 로직 (목표 달성 시 나머지 주문 취소)
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
                # 대기 중인 주문의 총 금액 합산
                pending_amt = sum(o['amt'] for o in pending_buys)
                
                # (보유액 + 대기액)이 목표액을 10% 이상 초과하면? -> 대기 주문 취소!
                # (이미 체결된 게 있어서 목표를 채웠다면, 남은 주문은 잉여입니다)
                if (current_amt + pending_amt) > (target_amt * 1.1):
                    print(f"   🚨 [Overbuy Guard] {t['name']} 목표 비중 충족 예상 -> 미체결 매수 취소")
                    
                    # 대기 중인 주문들 취소 실행
                    for order in pending_buys:
                        self.cancel_order(order['odno'], code)
                        # 리스트에서 제거 (역순 제거가 안전하지만, 여기선 pending_orders를 다시 로드하므로 pass)
                        # 텔레그램 알림
                        send_telegram_msg(f"🛡️ [과매수 방지] {t['name']} 미체결 주문 취소 (목표 달성)")
                    
                    # 큐 정리 (취소한 주문 제거)
                    self.pending_orders = [o for o in self.pending_orders if o not in pending_buys]
                    time.sleep(0.5)
        # ==================================================================

        current_time = time.time()

        # 3. Cleanup (미관리 종목 정리)
        target_codes = set([t['code'] for t in targets])
        for held_code, qty in holdings.items():
            if held_code not in target_codes:
                if any(p['code'] == held_code for p in self.pending_orders): continue
                exch = details.get(held_code, {}).get('exchange', 'NASD')
                price = self.get_current_price(held_code, exch)
                if price:
                    print(f"🧹 [Cleanup] {held_code} 전량 매도")
                    odno = self.send_order(held_code, 'SELL', price, qty, exch)
                    if odno:
                        send_telegram_msg(f"🇺🇸 [Cleanup] {held_code} 정리 매도 (주문: {odno})")
                        self.pending_orders.append({'odno': odno, 'code': held_code, 'name': held_code, 'type': 'SELL', 'qty': qty, 'amt': 0, 'time': time.time()})
                time.sleep(0.5)

        # ------------------------------------------------------------------
        # 4. [Parallel] 차트 데이터 갱신 (누락 종목 재시도 로직 강화)
        # ------------------------------------------------------------------
        is_regular_update = (current_time - self.last_chart_update_time) > self.CHART_REFRESH_INTERVAL
        
        # (1) 갱신할 대상 선정
        targets_to_fetch = targets if is_regular_update else [t for t in targets if t['code'] not in self.market_data_cache]

        # (2) 대상이 있을 때만 병렬 요청 실행
        if targets_to_fetch:
            if is_regular_update:
                print(f"\n🔄 [Update] 차트 데이터 정기 갱신 중... (전체)")
                self.last_chart_update_time = current_time # 정기 갱신일 때만 타이머 리셋
            else:
                print(f"\n⚠️ [Retry] 데이터 누락 종목 재시도 중... ({len(targets_to_fetch)}개)")

            # 병렬 작업 함수 정의
            def fetch_job(target):
                c = target['code']
                e = target.get('exchange', 'NASD')
                return c, self.get_daily_data(c, e)

            # ThreadPoolExecutor로 동시 요청
            with ThreadPoolExecutor(max_workers=5) as executor:
                future_to_stock = {executor.submit(fetch_job, t): t for t in targets_to_fetch}
                
                for future in as_completed(future_to_stock):
                    t = future_to_stock[future]
                    try:
                        code, data = future.result()
                        if data:
                            self.market_data_cache[code] = data
                            # print(f"   ✅ {code} 수신 완료")
                        else:
                            # 실패 시 로그만 남기고 다음 루프에서 다시 시도됨
                            pass
                    except Exception as e:
                        print(f"   ⚠️ [Error] {t['code']} 병렬 처리 중 에러: {e}")

        # 5. 자금 계산
        min_cash_ratio = getattr(Config, 'MIN_CASH_RATIO', 0.01)
        locked_cash = sum(o['amt'] for o in self.pending_orders if o['type'] == 'BUY')
        min_cash_needed = total_asset * min_cash_ratio
        investable_cash = total_cash - locked_cash - min_cash_needed
        if investable_cash < 0: investable_cash = 0

        # ✅ [포트폴리오 비중 콘솔 출력
        self.print_portfolio_log(total_asset, details, targets)
        print(f"\n💰 [Money] 보유: ${total_cash:,.2f} | 대기: ${locked_cash:,.2f} | 가용: ${investable_cash:,.2f}")

        # 6. 매매 루프
        for t in targets:
            code = t['code']
            exchange = t.get('exchange', 'NASD')
            if any(p['code'] == code for p in self.pending_orders): continue

            # [Step 1] 현재가 확인 (리밸런싱용)
            curr_price = self.get_current_price(code, exchange)
            if not curr_price: 
                print(f"   ⚠️ {code} 현재가 조회 실패")
                continue

            # [Step 2] 리밸런싱 (Rebalancing)
            qty_held = holdings.get(code, 0)
            target_amt = total_asset * t.get('target_ratio', 0)
            current_amt = qty_held * curr_price
            
            if qty_held > 0 and current_amt > (target_amt * 1.2):
                excess_amt = current_amt - target_amt
                sell_qty = int(excess_amt // curr_price)
                
                if sell_qty > 0:
                    print(f"   ⚖️ [Rebalance] {t['name']} 비중 초과 -> {sell_qty}주 매도")
                    odno = self.send_order(code, 'SELL', curr_price, sell_qty, exchange)
                    if odno == 'HOLIDAY':
                        print("   🛑 [Stop] 휴장일이므로 미국장 매매를 오늘 중단합니다.")
                        return "HOLIDAY"
                    elif odno:
                        # ✅ [텔레그램] 리밸런싱 알림
                        send_telegram_msg(f"⚖️ [리밸런싱] {t['name']} 비중 축소\n매도: {sell_qty}주 (@ ${curr_price})")
                        self.pending_orders.append({'odno': odno, 'code': code, 'name': t['name'], 'type': 'SELL', 'qty': sell_qty, 'amt': 0, 'time': time.time()})
                        investable_cash += (sell_qty * curr_price) # 현금 확보 반영
                        time.sleep(0.2)
                    continue
            
            # [Step 3] 차트 데이터 확인
            if code not in self.market_data_cache: continue

            # 지표 갱신
            if code not in self.market_data_cache: continue
            chart_data = self.market_data_cache[code][:]
            chart_data[-1]['Close'] = curr_price
            # 실시간 고가/저가 갱신
            if curr_price > chart_data[-1]['High']: chart_data[-1]['High'] = curr_price
            if curr_price < chart_data[-1]['Low']: chart_data[-1]['Low'] = curr_price
            
            df = self.calculate_indicators(chart_data)
            if df.empty: continue
            
            # 신호 판단
            signal, reason, _ = get_signal(t.get('strategy'), df.iloc[-1], df.iloc[-2], t.get('setting'))
            current_rsi = df.iloc[-1].get('RSI', 0)
            print(f"   🧐 {t['name']}({code}): ${curr_price} | RSI: {current_rsi:.1f} | Signal: {signal} ({reason})")
            # ------------------------------------------------------------------
            # [B] 매수 로직 (Buy)
            # ------------------------------------------------------------------
            if signal == 'buy':
                needed = target_amt - current_amt
                amt = min(needed, investable_cash)
                qty = int(amt // curr_price)
                
                if qty > 0:
                    print(f"   ⚡ [Buy Signal] {t['name']} {qty}주")
                    odno = self.send_order(code, 'BUY', curr_price, qty, exchange)
                    if odno == 'HOLIDAY':
                        print("   🛑 [Stop] 휴장일이므로 미국장 매매를 오늘 중단합니다.")
                        return "HOLIDAY"
                    elif odno:
                        # ✅ [텔레그램] 매수 접수 알림
                        send_telegram_msg(f"🚀 [매수 접수] {t['name']} {qty}주\n가격: ${curr_price} (Limit)")
                        self.pending_orders.append({'odno': odno, 'code': code, 'name': t['name'], 'type': 'BUY', 'qty': qty, 'price': curr_price, 'amt': qty*curr_price, 'time': time.time()})
                        investable_cash -= (qty * curr_price)

            # ------------------------------------------------------------------
            # [C] 매도 로직 (Sell)
            # ------------------------------------------------------------------
            elif signal == 'sell' and qty_held > 0:
                print(f"   ⚡ [Sell Signal] {t['name']} {qty_held}주")
                odno = self.send_order(code, 'SELL', curr_price, qty_held, exchange)
                if odno == 'HOLIDAY':
                    print("   🛑 [Stop] 휴장일이므로 미국장 매매를 오늘 중단합니다.")
                    return "HOLIDAY"
                elif odno:
                     # ✅ [텔레그램] 매도 접수 알림
                     send_telegram_msg(f"💧 [매도 접수] {t['name']} {qty_held}주 (전량)\n이유: {reason}")
                     self.pending_orders.append({'odno': odno, 'code': code, 'name': t['name'], 'type': 'SELL', 'qty': qty_held, 'amt': 0, 'time': time.time()})
          
        time.sleep(0.5)
        return "NORMAL"