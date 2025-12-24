import requests
import os
import json
import time
from config import Config
from src.traders.base_trader import BaseTrader
from src.data_manager import load_target_stocks
from src.strategy import get_signal # 👈 전략 함수 가져오기
from src.telegram_bot import send_telegram_msg
import csv
from datetime import datetime


class KoreaTrader(BaseTrader):
    def __init__(self, auth_manager):
        # 부모 클래스(BaseTrader) 초기화
        super().__init__(auth_manager)
        
        # ⏱️ 3시간 주기 리포트를 위한 타이머 (0으로 설정해 시작 즉시 발송 or time.time()으로 3시간 뒤)
        self.last_report_time = 0

    def get_balance(self):
        """[한국] 잔고 조회 (API 데이터 기반 수익금 상세 조회)"""
        path = "/uapi/domestic-stock/v1/trading/inquire-balance"
        tr_id = "VTTC8434R" if Config.MODE == 'PAPER' else "TTTC8434R"
        
        headers = {
            "authorization": f"Bearer {self.token}",
            "appkey": Config.APP_KEY,
            "appsecret": Config.APP_SECRET,
            "tr_id": tr_id
        }

        params = {
            "CANO": Config.ACCOUNT_NO, 
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
            res = requests.get(f"{Config.URL_BASE}{path}", headers=headers, params=params)
            data = res.json()
            
            if data['rt_cd'] == '0':
                out2 = data['output2'][0]
                
                # 1. 자산 및 현금 계산
                total_asset = float(out2.get('tot_evlu_amt', 0)) # 총 평가금액
                
                # ✅ [NEW] API 제공 수익금 데이터 추출
                # rlzt_pfls_amt: 실현손익 (오늘 팔아서 확정된 돈)
                # tot_evlu_pfls_amt: 평가손익 (안 팔고 들고 있는 종목들의 손익 합계)
                # asst_icdc_amt: 자산증감 (전일 대비 자산 변동액)
                
                balance_summary = {
                    "realized_profit": float(out2.get('rlzt_pfls_amt', 0)),
                    "eval_profit": float(out2.get('tot_evlu_pfls_amt', 0)),
                    "asset_change": float(out2.get('asst_icdc_amt', 0)),
                    "total_eval_profit": float(out2.get('tot_evlu_pfls_amt', 0)) # 호환성용
                }

                holdings = {}
                details = {}
                total_stock_value = 0
                
                for item in data['output1']:
                    qty = int(item['hldg_qty'])
                    if qty > 0:
                        code = item['pdno']
                        name = item['prdt_name']
                        avg_price = float(item['pchs_avg_pric'])
                        curr_price = float(item['prpr'])
                        eval_amt = float(item['evlu_amt'])
                        profit_rate = float(item['evlu_pfls_rt'])
                        profit_amt = float(item['evlu_pfls_amt'])

                        holdings[code] = qty
                        details[code] = {
                            "name": name, 
                            "qty": qty, 
                            "avg_price": avg_price, 
                            "curr_price": curr_price,
                            "eval_amt": eval_amt,
                            "profit_rate": profit_rate,
                            "profit_amt": profit_amt
                        }
                        total_stock_value += eval_amt
                        
                real_cash = total_asset - total_stock_value
                
                # ✅ 5번째 인자를 단순 float가 아닌 '상세 정보 딕셔너리'로 반환 (run 함수 호환성 유지)
                return total_asset, real_cash, holdings, details, balance_summary
                
            else:
                print(f"❌ [KR] 잔고 조회 실패: {data['msg1']}")
                # 실패 시 기본값 반환
                return 0.0, 0.0, {}, {}, {"realized_profit":0, "eval_profit":0, "asset_change":0}
                
        except Exception as e:
            print(f"⚠️ [KR] 잔고 로직 에러: {e}")
            return 0.0, 0.0, {}, {}, {"realized_profit":0, "eval_profit":0, "asset_change":0}

    def get_daily_data(self, code):
        """[한국] 일봉 데이터"""
        path = "/uapi/domestic-stock/v1/quotations/inquire-daily-price"
        headers = {
            "authorization": f"Bearer {self.token}",
            "appkey": Config.APP_KEY, 
            "appsecret": Config.APP_SECRET, 
            "tr_id": "FHKST01010400"
        }
        params = {
            "fid_cond_mrkt_div_code": "J", 
            "fid_input_iscd": code,
            "fid_input_cnt_1": "100", 
            "fid_org_adj_prc": "1",
            "fid_period_div_code": "D"
        }
        res = requests.get(f"{Config.URL_BASE}{path}", headers=headers, params=params)
        if res.status_code == 200:
            return [{
                "Date": r['stck_bsop_date'], 
                "Close": float(r['stck_clpr']),
                "Open": float(r['stck_oprc']), 
                "High": float(r['stck_hgpr']),
                "Low": float(r['stck_lwpr']),
                "Volume": int(r['acml_vol'])
            } for r in res.json().get('output', [])]
        return []

    def send_order(self, code, side, price, qty):
        """[한국] 주문"""
        path = "/uapi/domestic-stock/v1/trading/order-cash"
        tr_id = ("VTTC0012U" if side == 'BUY' else "VTTC0011U") if Config.MODE == 'PAPER' else ("TTTC0012U" if side == 'BUY' else "TTTC0011U")
        
        data = {
            "CANO": Config.ACCOUNT_NO, 
            "ACNT_PRDT_CD": "01", 
            "PDNO": code,
            "ORD_DVSN": "01", 
            "ORD_QTY": str(qty), 
            "ORD_UNPR": "0"
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

    def save_trade_log(self, type, name, price, qty, reason):
        """📝 거래 내용을 CSV 파일에 저장"""
        file_path = "data/trade_history.csv"
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if not os.path.exists(file_path):
            with open(file_path, mode='w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['Time', 'Type', 'Name', 'Price', 'Qty', 'Total_Amt', 'Reason'])

        with open(file_path, mode='a', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([now, type, name, price, qty, price*qty, reason])

    def report_targets(self):
        """장 시작 전: 목표 포트폴리오 보고"""
        targets = load_target_stocks("KR")

        if not targets:
            return "❌ [Error] 타겟 파일을 로드할 수 없습니다."
        
        # 1. 비중 계산
        total_stock_ratio = sum(t.get('target_ratio', 0) for t in targets)
        implied_cash_ratio = max(0, 1.0 - total_stock_ratio) # 남는 게 현금
        
        # 2. 메시지 작성
        msg = "☀️ **[오늘의 목표 포트폴리오]**\n"
        msg += f"🎯 주식 비중: {total_stock_ratio*100:.1f}%\n"
        msg += f"💵 현금 비중: {implied_cash_ratio*100:.1f}% (자동)\n\n"
        
        for t in targets:
            code = t['code']
            name = t['name']
            ratio = t.get('target_ratio', 0)
            strategy = t.get('strategy', 'Unknown')
            
            # 비율이 0인 관망 종목은 흐리게 표시
            if ratio > 0:
                icon = "🔹"
                ratio_str = f"{ratio*100:.1f}%"
            else:
                icon = "💤"
                ratio_str = "0.0% (관망)"
                
            msg += f"{icon} **{name}** ({code})\n"
            msg += f"   └ 비중: {ratio_str} | 전략: {strategy}\n"
            
        return msg
    
    def report_balance(self):
        """장 마감 후: API 데이터를 활용한 정확한 손익 보고"""
        self.refresh_token()
        
        # 1. 정보 조회 (5번째 인자가 이제 딕셔너리임)
        total_asset, total_cash, holdings, details, balance_summary = self.get_balance()
        
        # 2. API 데이터 추출
        realized_profit = balance_summary.get('realized_profit', 0)     # 실현손익
        eval_profit = balance_summary.get('eval_profit', 0)             # 평가손익
        asset_change = balance_summary.get('asset_change', 0)           # 자산증감(전일대비)
        
        # 실평가손익합계 (실현 + 평가)
        real_eval_sum = realized_profit + eval_profit

        # 3. 누적 수익률 계산 (JSON 활용)
        profit_file = "data/profit_status.json"
        
        if not os.path.exists(profit_file):
            init_data = {"initial_asset": total_asset, "last_update": ""}
            with open(profit_file, 'w', encoding='utf-8') as f:
                json.dump(init_data, f, indent=4)
                
        with open(profit_file, 'r', encoding='utf-8') as f:
            p_data = json.load(f)
            
        initial_asset = float(p_data.get('initial_asset', total_asset))
        
        # 누적 수익 (현재 자산 - 봇 시작 원금)
        total_profit = total_asset - initial_asset
        total_rate = (total_profit / initial_asset) * 100 if initial_asset > 0 else 0
        
        # 파일 업데이트
        p_data['last_update'] = time.strftime("%Y-%m-%d")
        with open(profit_file, 'w', encoding='utf-8') as f:
            json.dump(p_data, f, indent=4)
        
        # -----------------------------------------------------------
        # 📨 [보고서 작성] (요청하신 포맷 반영)
        # -----------------------------------------------------------
        msg = "🌙 **[장 마감 결산 보고]**\n"
        msg += f"💰 총 자산: {total_asset:,.0f}원\n"
        msg += f"💵 보유 현금: {total_cash:,.0f}원\n"
        msg += f"{'-'*25}\n"
        
        # 1) 실현손익 (Realized)
        icon_real = "💰" if realized_profit >= 0 else "💸"
        msg += f"{icon_real} **일간 실현:** {realized_profit:+,.0f}원\n"
        
        # 2) 평가손익 (Unrealized)
        icon_eval = "🔺" if eval_profit >= 0 else "🔻"
        msg += f"{icon_eval} **현재 평가:** {eval_profit:+,.0f}원\n"
        
        # 3) 실평가합계 (Realized + Unrealized)
        icon_sum = "🚀" if real_eval_sum >= 0 else "📉"
        msg += f"{icon_sum} **실평가합:** {real_eval_sum:+,.0f}원\n"

        # 4) 자산증감 (Asset Change vs Yesterday)
        icon_change = "📈" if asset_change >= 0 else "📉"
        msg += f"{icon_change} **자산증감:** {asset_change:+,.0f}원 (전일대비)\n"
        
        # 5) 누적 수익 (Total Cumulative)
        icon_total = "🔥" if total_profit >= 0 else "💧"
        msg += f"{icon_total} **누적 수익:** {total_profit:+,.0f}원 ({total_rate:+.2f}%)\n\n"
        
        msg += "**[보유 종목 상세]**\n"
        
        if not holdings:
            msg += "보유 중인 주식이 없습니다."
        else:
            sorted_codes = sorted(details.keys(), key=lambda x: details[x]['eval_amt'], reverse=True)
            for code in sorted_codes:
                info = details[code]
                ratio = (info['eval_amt'] / total_asset) * 100
                p_icon = "🔴" if info['profit_rate'] > 0 else "🔵"
                
                msg += f"{p_icon} **{info['name']}** {info['qty']}주 ({ratio:.1f}%)\n"
                msg += f"   └ {info['profit_rate']:+.2f}% ({info['profit_amt']:+,.0f}원)\n"

        return msg
    
    def report_portfolio_status(self):
        """📊 [3시간 주기] 텔레그램 리포트"""
        total_asset, total_cash, holdings, details, current_eval_profit = self.get_balance()
        targets = load_target_stocks("KR")
        if not targets: return

        total_stock_ratio = sum(t.get('target_ratio', 0) for t in targets)
        implied_cash_ratio = max(0, 1.0 - total_stock_ratio)
        target_cash = total_asset * implied_cash_ratio
        
        msg = f"📊 **[Portfolio Status]**\n"
        msg += f"자산: {total_asset:,.0f}원 | 현금: {total_cash:,.0f}원\n"
        msg += f"목표 주식: {total_stock_ratio*100:.1f}% | 목표 현금: {implied_cash_ratio*100:.1f}% ({target_cash:,.0f}원)\n"
        msg += f"{'종목명':<8} | {'수익률':^7} | {'평가금액':^10} | {'비중':^5}\n"
        msg += "-" * 35 + "\n"
        
        if details:
            sorted_codes = sorted(details.keys(), key=lambda x: details[x]['eval_amt'], reverse=True)
            for code in sorted_codes:
                info = details[code]
                target_r = 0
                for t in targets:
                    if t['code'] == code:
                        target_r = t.get('target_ratio', 0) * 100
                        break
                curr_ratio = (info['eval_amt'] / total_asset) * 100
                msg += f"{info['name']:<8} | {info['profit_rate']:>6.2f}% | {info['eval_amt']:>10,.0f}원 | {curr_ratio:>4.1f}%(목{target_r:.0f}%)\n"
        else:
            msg += "보유 종목 없음\n"
        
        msg += "-" * 35 + "\n"
        send_telegram_msg(msg)
    
    def print_portfolio_status(self, total_asset, total_cash, details, targets):
        """터미널 출력용 (Config 의존성 제거)"""
        print(f"\n📊 [Portfolio Status] 자산: {total_asset:,.0f}원 | 현금: {total_cash:,.0f}원")
        
        # 1. 타겟 비율 기반으로 목표 현금 계산
        total_stock_ratio = sum(t.get('target_ratio', 0) for t in targets)
        implied_cash_ratio = max(0, 1.0 - total_stock_ratio)
        target_cash = total_asset * implied_cash_ratio
        
        print(f"   목표 주식: {total_stock_ratio*100:.1f}% | 목표 현금: {implied_cash_ratio*100:.1f}% ({target_cash:,.0f}원)")

        if not details:
            print("   보유 종목 없음")
        else:
            print(f"   {'종목명':<10} | {'수익률':^8} | {'평가금액':^12} | {'비중':^6}")
            print("-" * 50)
            for code, info in details.items():
                name = info['name']
                rate = info['profit_rate']
                eval_amt = info['eval_amt']
                ratio = (eval_amt / total_asset) * 100
                
                # 목표 비중 찾기
                target_r = 0
                for t in targets:
                    if t['code'] == code:
                        target_r = t.get('target_ratio', 0) * 100
                        break
                
                print(f"   {name:<10} | {rate:>6.2f}% | {eval_amt:>11,.0f}원 | {ratio:>5.1f}% (목표 {target_r:.1f}%)")
        print("-" * 50)

    def run(self):
        """한국장 통합 매매 로직 (Cleanup + Cash Safety + Rebalancing)"""
        self.refresh_token()
        
        # 1. 자산 및 타겟 로드
        total_asset, total_cash, holdings, details, all_pfls_dict = self.get_balance()
        targets = load_target_stocks("KR")

        # 🚨 [안전장치] 타겟 로드 실패 시 로직 중단
        if not targets:
            print("🚨 [Critical] 타겟 종목 로드 실패! 매매를 중단합니다.")
            send_telegram_msg("🚨 [Error] 타겟 설정 파일이 비어있거나 로드할 수 없습니다. 봇을 점검하세요.")
            return
        
        # ---------------------------------------------------------
        # ⏰ 3시간 주기 리포트 체크
        # ---------------------------------------------------------
        if time.time() - self.last_report_time >= 10800: # 3시간 = 10800초
            print("⏰ [알림] 3시간 정기 리포트 전송 중...")
            self.report_portfolio_status()
            self.last_report_time = time.time() # 타이머 리셋

        # ---------------------------------------------------------
        # 🧹 [Cleanup] 미관리 종목 정리 (JSON에 없는 종목 매도)
        # ---------------------------------------------------------
        target_codes = set([t['code'] for t in targets])
        for held_code, qty in holdings.items():
            if held_code not in target_codes:
                raw_data = self.get_daily_data(held_code)
                if raw_data:
                    curr_price = int(raw_data[0]['Close'])
                    print(f"🧹 [Cleanup] 제외된 종목 발견: {held_code} -> 전량 매도")
                    if self.send_order(held_code, 'SELL', curr_price, qty):
                        # ✅ 로그 저장 및 알림
                        self.save_trade_log("Sell(Cleanup)", held_code, curr_price, qty, "타겟제외")
                        send_telegram_msg(f"🧹 [Cleanup] {held_code} 전량 매도 완료\n수량: {qty}주 | 가격: {curr_price:,}원")
                        total_cash += (qty * curr_price)
                time.sleep(0.2)

        # ---------------------------------------------------------
        # 🛡️ [Validation] 포트폴리오 비율 검증
        # ---------------------------------------------------------
        total_stock_ratio = sum(t.get('target_ratio', 0) for t in targets)
        
        if total_stock_ratio > 1.05: # 합계가 100%를 많이 넘으면 경고
            print(f"🚨 [경고] 목표 비율 합계 초과! ({total_stock_ratio*100:.1f}%)")

        investable_cash = total_cash 

        self.print_portfolio_status(total_asset, total_cash, details, targets)
        print(f"   목표 주식 비중: {total_stock_ratio*100:.1f}%")

        # ---------------------------------------------------------
        # 🚀 [Main Loop] 종목별 매매 수행
        # ---------------------------------------------------------
        for t in targets:
            code = t['code']
            name = t['name']
            target_ratio = t.get('target_ratio', 0)
            target_amt = total_asset * target_ratio # 목표 보유 금액

            # 데이터 조회
            raw_data = self.get_daily_data(code)

            if not raw_data: 
                continue

            # 지표 계산
            df = self.calculate_indicators(raw_data)
            if df.empty: continue
            
            curr, prev = df.iloc[-1], df.iloc[-2]
            current_price = int(curr['Close'])
            
            # 전략 신호 확인
            strategy_name = t.get('strategy', 'MACD_RSI')
            setting = t.get('setting', {})
            signal, reason, _ = get_signal(strategy_name, curr, prev, setting)
            
            qty_held = holdings.get(code, 0)
            current_amt = qty_held * current_price

            # [A] 리밸런싱 (비중이 너무 커졌을 때) 목표 금액보다 20% 초과 시 초과분 매도
            if qty_held > 0 and current_amt > (target_amt * 1.2):
                excess_amt = current_amt - target_amt
                sell_qty = int(excess_amt // current_price)
                if sell_qty > 0:
                    print(f"   ⚖️ [{name}] 비중 초과 리밸런싱: {sell_qty}주 매도")
                    if self.send_order(code, 'SELL', current_price, sell_qty):
                        # ✅ 저장 및 텔레그램 발송
                        self.save_trade_log("Sell(Rebalance)", name, current_price, sell_qty, "비중초과")
                        send_telegram_msg(f"⚖️ [리밸런싱 매도] {name}\n수량: {sell_qty}주\n가격: {current_price:,}원\n이유: 비중 초과")
                        investable_cash += (sell_qty * current_price)
                        total_cash += (sell_qty * current_price)

            # [B] 매수 로직 (신호 + 비중 부족 + 현금 여유)
            if signal == 'buy':
                needed_amt = target_amt - current_amt # 채워야 할 금액
                
                # 살 필요가 있고, 1주라도 살 돈이 될 때
                if needed_amt >= current_price:
                    # 현금 방어벽 확인
                    if investable_cash < current_price:
                        print(f"   🔒 [{name}] 매수 스킵 (현금 비중 보호)(현금 부족: {investable_cash:,.0f}원)")
                        continue
                    
                    # 예산 조정 (가용 현금 안에서만)
                    if needed_amt > investable_cash:
                        needed_amt = investable_cash
                    
                    buy_qty = int(needed_amt // current_price)
                    if buy_qty > 0:
                        print(f"   🚀 [{name}] 매수: {buy_qty}주 (목표비중 {target_ratio*100}%, 전략: {strategy_name})")
                        if self.send_order(code, 'BUY', current_price, buy_qty):
                            # ✅ 저장 및 텔레그램 발송
                            self.save_trade_log("Buy", name, current_price, buy_qty, strategy_name)
                            send_telegram_msg(f"🚀 [매수] {name} {buy_qty}주 체결")
                            investable_cash -= (buy_qty * current_price)
                            total_cash -= (buy_qty * current_price)

            # [C] 매도 로직 (전략적 매도 신호 시 전량 매도)
            elif signal == 'sell': 
                if qty_held > 0:
                    print(f"   💧 [{name}] 전량 매도: {qty_held}주 ({reason})")
                    if self.send_order(code, 'SELL', current_price, qty_held):
                        # ✅ 텔레그램 발송
                        self.save_trade_log("Sell", name, current_price, qty_held, reason)
                        send_telegram_msg(f"💧 [매도] {name} {qty_held}주 체결 ({reason})")
                        investable_cash += (qty_held * current_price)
                        total_cash += (qty_held * current_price)

            time.sleep(0.5)