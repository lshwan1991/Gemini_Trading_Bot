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

    # ==================================================================
    # [Core] 자산 및 현재가 조회
    # =================================================================
    def get_balance(self):
        """[메인] 자산 조회 (현금 & 보유주식)"""
        print("\n🔍 [System] 자산 현황 갱신 중 (Cash & Holdings 분리 조회)...")
        self.total_usd = self._fetch_cash_balance()
        self.holdings, stock_details = self._fetch_stock_holdings()
        
        total_stock_val = sum(d['eval_amt'] for d in stock_details.values())
        self.total_asset = self.total_usd + total_stock_val
        
        # 현금 비중 계산
        cash_ratio = (self.total_usd / self.total_asset * 100) if self.total_asset > 0 else 0.0
        
        print(f"   💰 [Total Asset] 총 자산: ${self.total_asset:,.2f} (현금비중: {cash_ratio:.1f}%)")
        return self.total_asset, self.total_usd, self.holdings, stock_details

    def get_current_price(self, code, exchange="NASD"):
        """[미국] 실시간 현재가 조회 (세션 적용 버전)"""
        lookup_exch = "NAS"
        if exchange in ["NYSE", "NYS"]: lookup_exch = "NYS"
        if exchange in ["AMEX", "AMS"]: lookup_exch = "AMS"

        path = "/uapi/overseas-price/v1/quotations/price"
        headers = {
            "authorization": f"Bearer {self.token}",
            "appkey": self.app_key, 
            "appsecret": self.app_secret,
            "tr_id": "HHDFS00000300"
        }
        params = {"AUTH": "", "EXCD": lookup_exch, "SYMB": code}
        
        try:
            # ✅ requests.get -> self.session.get 으로 변경
            # timeout을 설정하여 무한 대기 방지 (2초)
            res = self.session.get(f"{self.url_base}{path}", headers=headers, params=params, timeout=2)
            
            if res.status_code == 200:
                try:
                    data = res.json()
                    if data['rt_cd'] == '0':
                        return float(data['output']['last'])
                    else:
                        # 토큰 만료 등 API 에러 처리
                        if "만료" in data['msg1']:
                            self.force_refresh_token()
                        return None
                except json.JSONDecodeError:
                    print(f"⚠️ [Price Error] {code}: JSON 디코딩 실패 (빈 응답)")
                    return None
            else:
                print(f"⚠️ [Price Error] {code}: Status {res.status_code}")
                return None

        except Exception as e:
            # 세션이 재시도했음에도 실패한 경우
            print(f"⚠️ [Price Error] {code}: {e}")
            return None

    def _fetch_cash_balance(self, retry=True):
        """[Sub] 해외증거금 조회 (Buying Power)"""
        print("   📡 [Cash] Buying Power 조회 중...", end='')
        path = "/uapi/overseas-stock/v1/trading/foreign-margin"
        headers = {
            "authorization": f"Bearer {self.token}", 
            "appkey": self.app_key, 
            "appsecret": self.app_secret,
            "tr_id": "TTTC2101R", 
            "custtype": "P"
        }
        params = {"CANO": self.account_no, "ACNT_PRDT_CD": "01"}

        try:
            res = requests.get(f"{self.url_base}{path}", headers=headers, params=params)
            data = res.json()
            if data['rt_cd'] == '0':
                output_list = data.get('output', [])
                for item in output_list:
                    if item.get('crcy_cd') == 'USD':
                        val = float(item.get('frcr_gnrl_ord_psbl_amt', 0))
                        print(f" 성공! (${val:,.2f})")
                        return val
                print(" 실패 (USD 없음)")
                return 0.0
            else:
                msg = data['msg1']
                # ✅ [복구] 토큰 만료 시 자동 갱신
                if retry and ("만료" in msg or "token" in msg.lower()):
                    print(f" ⚠️ [Token Expired] 토큰 만료됨. 재발급 후 다시 조회합니다...")
                    self.force_refresh_token()
                    return self._fetch_cash_balance(retry=False)
                # print(f" 실패 ({msg})")
                print(f" 실패 ({data['msg1']})")
                return 0.0
        except:
            return 0.0
        
    def _fetch_stock_holdings(self, retry=True):
        """[Sub] 보유주식 상세 조회 (거래소 정보 포함)"""
        path = "/uapi/overseas-stock/v1/trading/inquire-balance"
        tr_id = "VTTS3012R" if self.mode == 'PAPER' else "TTTS3012R"
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
            "TR_CRCY_CD": "USD", 
            "CTX_AREA_FK200": "", 
            "CTX_AREA_NK200": ""
        }
        
        holdings = {}
        details = {}
        try:
            res = requests.get(f"{self.url_base}{path}", headers=headers, params=params)
            data = res.json()
            if data['rt_cd'] == '0':
                for item in data.get('output1', []):
                    qty = int(float(item['ovrs_cblc_qty']))
                    if qty > 0:
                        code = item['ovrs_pdno']
                        holdings[code] = qty
                        details[code] = {
                            "name": item['ovrs_item_name'], 
                            "qty": qty,
                            "curr_price": float(item['now_pric2']),      # 현재가
                            "avg_price": float(item['pchs_avg_pric']),   # 평단가 (추가)
                            "eval_amt": float(item['frcr_evlu_amt2']),   # 평가금액
                            "profit_rate": float(item['evlu_pfls_rt']),  # 수익률 (추가)
                            "exchange": item.get('ovrs_excg_cd', 'NASD') # 거래소
                        }
                return holdings, details
            else:
                msg = data['msg1']
                if retry and ("만료" in msg or "token" in msg.lower()):
                    print(f" ⚠️ [Token Expired] 재발급 후 보유내역 다시 조회합니다...")
                    self.force_refresh_token()
                    return self._fetch_stock_holdings(retry=False)
                return {}, {}
        except:
            return {}, {}
    
    def force_refresh_token(self):
        """🚨 토큰 강제 갱신 헬퍼 함수"""
        file_name = f"data/token_{self.mode.lower()}.json"
        if os.path.exists(file_name):
            os.remove(file_name)
        self.refresh_token()

    def get_daily_data(self, code, exchange="NASD"):
        """[미국] 일봉 데이터 조회 (세션 & 타임아웃 적용)"""
        lookup_exch = "NAS"
        if exchange in ["NYSE", "NYS"]: lookup_exch = "NYS"
        elif exchange in ["AMEX", "AMS"]: lookup_exch = "AMS"

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
            # ✅ [핵심] timeout=2 설정 (2초 안에 답 없으면 바로 에러 처리하고 넘어감)
            res = self.session.get(f"{self.url_base}{path}", headers=headers, params=params, timeout=2)
            
            if res.status_code == 200 and res.json()['rt_cd'] == '0':
                items = res.json().get('output2', [])
                if items:
                    # print(f"   📊 [Data] {code} 수신 완료") # 로그 너무 많으면 주석 처리
                    return [{
                        "Date": item['xymd'], "Close": float(item['clos']),
                        "Open": float(item['open']), "High": float(item['high']),
                        "Low": float(item['low']), "Volume": int(float(item['tvol']))
                    } for item in items]
            return []
        except Exception as e:
            # 병렬 처리 중 에러 로그는 run()에서 취합해서 보여줄 수도 있음
            # print(f"⚠️ [Data Error] {code}: {e}")
            return []
        
    # ==================================================================
    # [Order] 주문 실행
    # ==================================================================
    def send_order(self, code, side, price, qty, exchange="NASD"):
        """[미국] 주문 전송 (지정가 0.5% 보정 + 거래소 코드 자동 변환)"""
        # 1. 거래소 코드 변환
        target_exch = "NASD" # 기본값
        ex_upper = exchange.upper()

        if ex_upper in ["NYSE", "NYS", "NEWYORK"]:
            target_exch = "NYSE"
        elif ex_upper in ["AMEX", "AMS"]:
            target_exch = "AMEX"
        else:
            target_exch = "NASD" # NAS, NASDAQ 등은 NASD로 통일

        # 가격 보정 (즉시 체결 유도)
        if side == 'BUY':
            limit_price = round(price * 1.005, 2) # 1.01 -> 1.005
        else:
            limit_price = round(price * 0.995, 2) # 0.99 -> 0.995

        print(f"   📡 [Sending] {side} {code} {qty}주 @ ${limit_price} (지정가/0.5%보정) (Exch: {target_exch})")

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
            "OVRS_ORD_UNPR": str(limit_price),
            "ORD_SVR_DVSN_CD": "0", 
            "ORD_DVSN": "00" #00 지정가
        }
        
        headers = {
            "authorization": f"Bearer {self.token}", 
            "appkey": self.account_no, 
            "appsecret": self.app_secret,
            "tr_id": tr_id, 
            "hashkey": self.auth_manager.get_hashkey(data)
        }
        
        try:
            res = requests.post(f"{self.url_base}{path}", headers=headers, data=json.dumps(data))
            if res.status_code == 200 and res.json()['rt_cd'] == '0':
                odno = res.json()['output']['ODNO']
                print(f"   ✅ [Accepted] 주문 접수 완료 (No: {odno})")
                return odno
            
            else:
                msg = res.json().get('msg1', '')
                # ✅ 미국장 휴장일 메시지 감지 (거부 사유 확인 필요)
                # 보통 "장운영 시간이 아닙니다" 혹은 "Reject" 등이 
                if "장운영" in msg or "Closed" in msg or "Holiday" in msg:
                     print(f"   😴 [Holiday] 미국장 휴장 감지! {msg}")
                     return 'HOLIDAY'
                
                elif "만료" in msg:
                    print("   ⚠️ [Token] 주문 중 토큰 만료! 재시도 필요")
                    self.force_refresh_token()
                else:
                    print(f"   ❌ [Failed] 주문 실패: {msg}")
                return None
            
        except Exception as e:
            print(f"   ⚠️ [API Error] {e}")
            return None

    def get_unfilled_orders(self):
        """미체결 내역 조회"""
        path = "/uapi/overseas-stock/v1/trading/inquire-nccs"
        tr_id = "VTTS3018R" if self.mode == 'PAPER' else "TTTS3018R"
        headers = {
            "authorization": f"Bearer {self.token}", "appkey": self.app_key, "appsecret": self.app_secret, "tr_id": tr_id
        }
        params = {
            "CANO": self.account_no, "ACNT_PRDT_CD": "01", "OVRS_EXCG_CD": "NASD",
            "SORT_SQN": "DS", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
        }
        try:
            res = requests.get(f"{self.url_base}{path}", headers=headers, params=params)
            unfilled_list = []
            if res.json()['rt_cd'] == '0':
                for item in res.json().get('output', []):
                    remain = int(item['ord_qty']) - int(item['ccld_qty'])
                    if remain > 0:
                        unfilled_list.append({
                            "odno": item['odno'], "code": item['pdno'], "qty": remain, "price": item['ord_unpr']
                        })
            return unfilled_list
        except:
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
        """대기열 관리"""
        if not self.pending_orders: return
        print(f"\n📋 [Queue] 미체결 주문 {len(self.pending_orders)}건 확인 중...")
        unfilled_list = self.get_unfilled_orders() 
        
        for i in range(len(self.pending_orders) - 1, -1, -1):
            order = self.pending_orders[i]
            if time.time() - order['time'] > 60: # 60초 초과 시 취소
                print(f"      ⏰ Timeout -> 취소 실행")
                self.cancel_order(order['odno'], order['code'])
                self.pending_orders.pop(i)
                continue
            
            is_unfilled = any(u['odno'] == order['odno'] for u in unfilled_list)
            if not is_unfilled:
                print(f"   🎉 [Filled] {order['name']} 체결 완료!")
                # ✅ [텔레그램] 체결 알림
                send_telegram_msg(f"🇺🇸 [체결 알림] {order['name']} {order['type']} 완료!\n(주문번호: {order['odno']})")
                self.pending_orders.pop(i)

    # ==================================================================
    # [Report] 포트폴리오 보고서
    # ==================================================================
    def report_targets(self):
        """장 시작 전 보고 (main_controller 호출용)"""
        targets = load_target_stocks("US")
        if not targets: return "❌ [Error] 타겟 파일 로드 실패"
        
        total_ratio = sum(t.get('target_ratio', 0) for t in targets)
        
        msg = f"☀️ **[오늘의 목표 포트폴리오 (US)]**\n"
        msg += f"🎯 주식 비중: {total_ratio*100:.1f}%\n\n"
        
        for t in targets:
            exch = t.get('exchange', 'NASD') # 거래소 정보 표시
            msg += f"🔹 {t['name']} ({t['code']}/{exch}): {t.get('target_ratio',0)*100:.1f}%\n"
            
        return msg
    
    def report_balance(self):
        """🌙 [Report] 장 마감 결산 보고"""
        self.refresh_token()
        
        # 1. 자산 조회
        total_asset, total_usd, holdings, details = self.get_balance()
        
        # 2. 총 평가 손익 계산 (미국장은 실현손익 API가 복잡하여 평가손익 위주로 표기)
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
            msg += "**[보유 종목 상세]**\n"
            sorted_codes = sorted(details.keys(), key=lambda x: details[x]['eval_amt'], reverse=True)
            
            for code in sorted_codes:
                info = details[code]
                
                # 비중
                weight = (info['eval_amt'] / total_asset * 100) if total_asset > 0 else 0
                
                # 아이콘
                icon = "🔴" if info['profit_rate'] > 0 else "🔵"
                
                # 평가손익 금액 (현재가치 - 매수금액)
                profit_amt = info['eval_amt'] - (info['avg_price'] * info['qty'])
                
                msg += f"{icon} **{info['name']}** ({code})\n"
                msg += f"   • 수익: ${profit_amt:+,.2f} ({info['profit_rate']:+.2f}%)\n"
                msg += f"   • 단가: ${info['avg_price']:,.2f} → ${info['curr_price']:,.2f}\n"
                msg += f"   • 비중: {weight:.1f}% (${info['eval_amt']:,.2f})\n\n"
        else:
            msg += "보유 주식 없음 (100% 현금)\n"
            
        return msg
    
    def report_portfolio_status(self):
        """📊 생존 신고 + [Report] 3시간 주기 텔레그램 리포트"""
        total_asset, total_usd, holdings, details = self.get_balance()
        targets = load_target_stocks("US")
        
        # 현금 비중
        cash_ratio = (total_usd / total_asset * 100) if total_asset > 0 else 0
        
        msg = f"🇺🇸 **[생존 알림 + Portfolio Status]**\n"
        msg += f"💰 총자산: ${total_asset:,.2f}\n"
        msg += f"💵 현금: ${total_usd:,.2f} ({cash_ratio:.1f}%)\n"
        msg += "-" * 30 + "\n"
        
        # 3. 보유 종목 리스팅
        if details:
            # 평가금액 순 정렬
            sorted_codes = sorted(details.keys(), key=lambda x: details[x]['eval_amt'], reverse=True)
            
            for code in sorted_codes:
                info = details[code]
                
                # 목표 비중 찾기
                target_ratio = 0
                for t in targets:
                    if t['code'] == code:
                        target_ratio = t.get('target_ratio', 0)
                        break
                
                # 현재 비중 계산
                current_ratio = (info['eval_amt'] / total_asset) * 100
                target_ratio_pct = target_ratio * 100
                
                # 수익/손실 아이콘
                icon = "🔴" if info['profit_rate'] > 0 else "🔵"
                
                # 메시지 포맷팅 (KR과 통일)
                msg += f"{icon} **{info['name']}** ({code})\n"
                msg += f"   • 수익: {info['profit_rate']:+.2f}%  |  ${info['eval_amt']:,.2f}\n"
                msg += f"   • 단가: ${info['avg_price']:,.2f} → ${info['curr_price']:,.2f}\n"
                msg += f"   • 비중: {current_ratio:.1f}% (목표 {target_ratio_pct:.0f}%)\n"
                msg += "-" * 30 + "\n"
        else:
            msg += "💤 보유 중인 미국 주식이 없습니다.\n"
        
        send_telegram_msg(msg)

    def print_portfolio_log(self, total_asset, details, targets):
        """📝 [Log] 포트폴리오 비중 콘솔 출력"""
        print("\n📊 [Portfolio Status]")
        print(f"   {'종목명':<10} | {'평가금액($)':^12} | {'현재비중':^8} | {'목표비중':^8}")
        print("-" * 55)
        
        for t in targets:
            code = t['code']
            name = t['name']
            target_r = t.get('target_ratio', 0) * 100
            
            info = details.get(code, {'eval_amt': 0})
            curr_val = info.get('eval_amt', 0)
            curr_r = (curr_val / total_asset * 100) if total_asset > 0 else 0
            
            print(f"   {name:<10} | {curr_val:>11,.2f} | {curr_r:>7.1f}% | {target_r:>7.1f}%")
        print("-" * 55)

    # ==================================================================
    # [Main Logic] 봇 실행
    # ==================================================================
    def run(self):
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

        #[Parallel] 차트 데이터 병렬 갱신 (핵심 ⭐)
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
        targets_to_fetch = []
        
        if is_regular_update:
            # 정기 갱신 주기(10분)가 되었으면 -> 모든 타겟 추가
            targets_to_fetch = targets
        else:
            # 정기 갱신 아님 -> 캐시에 데이터가 없는(실패한) 종목만 골라서 추가 (패자부활전)
            for t in targets:
                if t['code'] not in self.market_data_cache:
                    targets_to_fetch.append(t)

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

        # ✅ [Log] 포트폴리오 비중 콘솔 출력
        self.print_portfolio_log(total_asset, details, targets)
        print(f"\n💰 [Money] 보유: ${total_cash:,.2f} | 대기: ${locked_cash:,.2f} | 가용: ${investable_cash:,.2f}")

        # 6. 매매 루프
        for t in targets:
            code = t['code']
            exchange = t.get('exchange', 'NASD')
            if any(p['code'] == code for p in self.pending_orders): continue

            # [Step 1] 현재가 확인 (리밸런싱용)
            curr_price = self.get_current_price(code, exchange)
            if not curr_price: continue

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
            chart_data = self.market_data_cache[code][:]
            if chart_data:
                chart_data[-1]['Close'] = curr_price
                if curr_price > chart_data[-1]['High']: chart_data[-1]['High'] = curr_price
                if curr_price < chart_data[-1]['Low']: chart_data[-1]['Low'] = curr_price
            
            df = self.calculate_indicators(chart_data)
            if df.empty: continue
            
            # 신호 판단
            signal, reason, _ = get_signal(t.get('strategy'), df.iloc[-1], df.iloc[-2], t.get('setting'))

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
                        time.sleep(0.5)
            
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
          
        time.sleep(0.5)
        return "NORMAL"