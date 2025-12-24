import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os
import glob

# ==========================================
# 1. 전략 함수 정의 (최종 튜닝 버전)
# ==========================================

def strat_macd_rsi_optimized(curr, prev, setting):
    """[전략] MACD + RSI + 이동평균선 필터"""
    if pd.isna(curr.get('SMA60')) or pd.isna(curr.get('RSI')) or pd.isna(curr.get('MACD')):
        return 'none', '데이터부족', 0

    rsi_sell = setting.get('rsi_sell', 70)
    
    is_golden_cross = (prev['MACD'] < prev['Signal']) and (curr['MACD'] > curr['Signal'])
    is_dead_cross = (prev['MACD'] > prev['Signal']) and (curr['MACD'] < curr['Signal'])
    is_uptrend = curr['Close'] > curr['SMA60']
    
    # [매수]
    if is_golden_cross and curr['RSI'] < 70 and is_uptrend:
        return 'buy', "MACD_골든크로스(추세장)", 0

    # [매도]
    if curr['RSI'] > rsi_sell: return 'sell', "RSI_과열_익절", 0
    if is_dead_cross: return 'sell', "MACD_데드크로스", 0
    if curr['Close'] < curr['SMA60']: return 'sell', "추세이탈(SMA60)_매도", 0

    return 'none', '', 0

def strat_smart_momentum(curr, prev, setting):
    """[전략] 스마트 모멘텀 (추세 추종 강화형)"""
    # 데이터 검증
    if pd.isna(curr.get('SMA20')) or pd.isna(curr.get('Range')) or pd.isna(curr.get('Open')):
        return 'none', '데이터부족', 0

    if 'NoiseMA20' in curr and not pd.isna(curr['NoiseMA20']):
        k = curr['NoiseMA20']
    else:
        k = setting.get('k', 0.5)
        
    k = max(0.3, min(0.7, k))
    
    target_price = curr['Open'] + (curr['Range'] * k)
    current_price = curr['Close'] 
    
    is_bull_market = current_price > curr['SMA20']
    volume_condition = curr['Volume'] > prev['Volume'] * 0.8
    
    # 🟢 [매수 신호]
    break_success = False
    if curr['High'] > target_price: 
        break_success = True

    if break_success and is_bull_market and volume_condition:
         return 'buy', f"스마트_돌파(k={k:.2f},Vol_OK)", 0

    # 🔴 [매도 신호] (SMA5 삭제, RSI 상향)
    # 1. RSI 과열 익절 (85로 상향)
    if curr.get('RSI', 50) > 85:
        return 'sell', "RSI초과열(85)_익절", 0

    # 2. SMA5 트레일링 스톱 -> 삭제함 (추세 길게 가져가기 위해)

    # 3. 20일선 이탈 (Buffer 1% 유지)
    sma20_buffer = curr['SMA20'] * 0.99
    if current_price < sma20_buffer:
        return 'sell', "추세이탈(SMA20)_매도", 0
        
    return 'none', '', 0

def get_signal(strategy_name, curr, prev, setting):
    try:
        if strategy_name == "MACD_RSI_OPTIMIZED" or strategy_name == "MACD_RSI":
            return strat_macd_rsi_optimized(curr, prev, setting)
        if strategy_name == "SMART_MOMENTUM":
            return strat_smart_momentum(curr, prev, setting)
        return 'none', '', 0 
    except Exception as e:
        print(f"⚠️ 전략 에러: {e}")
        return 'none', '에러발생', 0

# ==========================================
# ⚙️ 설정: 5차 테스트 비율 (2:2:2:2:2)
# ==========================================
PORTFOLIO = {
    # [대형주: MACD_RSI_OPTIMIZED]
    "005930": {"name": "삼성전자", "strategy": "MACD_RSI_OPTIMIZED", "ratio": 0.2, "rsi_sell": 75},
    
    # [ETF: SMART_MOMENTUM]
    "252670": {"name": "인버스2X", "strategy": "SMART_MOMENTUM", "ratio": 0.05, "k": 0.4},
    "122630": {"name": "레버리지", "strategy": "SMART_MOMENTUM", "ratio": 0.05, "k": 0.4},
    
    # [중소형주: SMART_MOMENTUM]
    "107640": {"name": "한중엔시에스", "strategy": "SMART_MOMENTUM", "ratio": 0.2, "k": 0.7},
    "017960": {"name": "한국카본", "strategy": "SMART_MOMENTUM", "ratio": 0.2, "k": 0.7},
}

INIT_BALANCE = 10000000  
COMMISSION_ETF = 0.00015 
COMMISSION_STK = 0.0023  
SLIPPAGE = 0.002 

# ==========================================
# 🧠 지표 계산 및 백테스트 엔진
# ==========================================
def calculate_indicators(df):
    df['SMA5'] = df['Close'].rolling(window=5).mean()
    df['SMA20'] = df['Close'].rolling(window=20).mean()
    df['SMA60'] = df['Close'].rolling(window=60).mean()
    
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    exp12 = df['Close'].ewm(span=12, adjust=False).mean()
    exp26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp12 - exp26
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    
    df['Range'] = df['High'] - df['Low']
    range_k = df['Range'].replace(0, 1)
    df['Noise'] = 1 - (abs(df['Open'] - df['Close']) / range_k)
    df['NoiseMA20'] = df['Noise'].rolling(window=20).mean()
    
    return df

def run():
    files = glob.glob("history_data_backtest/*.csv")
    if not files: return

    data_map = {}
    print(f"🔄 데이터 로딩 중... ({len(files)}개)")
    for f in files:
        code = os.path.basename(f).replace('.csv', '')
        if code not in PORTFOLIO: continue
        df = pd.read_csv(f, parse_dates=['Date'], index_col='Date')
        df = calculate_indicators(df)
        data_map[code] = df

    if not data_map: return
    all_dates = sorted(list(set.union(*[set(df.index) for df in data_map.values()])))
    balance = INIT_BALANCE
    holdings = {code: 0 for code in PORTFOLIO}
    avg_price = {code: 0 for code in PORTFOLIO}
    daily_history = []
    trade_logs = [] 

    print(f"🚀 백테스트 시작! (기간: {all_dates[0].date()} ~ {all_dates[-1].date()})")
    print("-" * 85)
    print(f"{'날짜':<12} | {'유형':<4} | {'종목명':<10} | {'체결가':>8} | {'수량':>5} | {'수익률/이유':<15}")
    print("-" * 85)
    
    for i in range(1, len(all_dates)):
        today = all_dates[i]
        prev_day = all_dates[i-1]
        date_str = today.strftime('%Y-%m-%d')
        
        # 1. 자산 평가
        current_equity = balance
        for code, qty in holdings.items():
            if qty > 0 and today in data_map[code].index:
                current_equity += qty * data_map[code].loc[today]['Close']
        daily_log = {'Date': today, 'TotalAsset': current_equity}
        
        # 2. 매매 루프
        for code, setting in PORTFOLIO.items():
            if code not in data_map: continue
            df = data_map[code]
            if today not in df.index or prev_day not in df.index: continue
            
            curr = df.loc[today].copy() 
            prev = df.loc[prev_day]
            curr_close = curr['Close']
            
            # ---------------------------------------------------
            # ✅ [A] 리밸런싱 로직
            # ---------------------------------------------------
            target_amt = current_equity * setting['ratio']
            current_amt = holdings[code] * curr_close
            is_etf = "KODEX" in setting.get('strategy', '') or code in ["122630", "252670"] 
            fee = COMMISSION_ETF if is_etf else COMMISSION_STK
            name = setting['name']

            # 목표보다 20% 초과 보유 시 -> 초과분 매도
            if holdings[code] > 0 and current_amt > (target_amt * 1.2):
                excess_amt = current_amt - target_amt
                sell_qty = int(excess_amt // curr_close)
                
                if sell_qty > 0:
                    revenue = sell_qty * curr_close
                    balance += revenue * (1 - fee)
                    holdings[code] -= sell_qty
                    
                    # 🔹 리밸런싱 로그 출력
                    print(f"{date_str} | ⚖️ 조절 | {name:<10} | {curr_close:>8,.0f} | {sell_qty:>5} | 비중초과 매도")
                    trade_logs.append({'Date': date_str, 'Type': 'Rebalance', 'Name': name, 'Price': curr_close, 'Qty': sell_qty, 'Profit': 0, 'Reason': '비중초과'})
                    
                    current_equity = balance + sum(holdings[c] * data_map[c].loc[today]['Close'] for c in holdings if c in data_map and today in data_map[c].index)

            # ---------------------------------------------------
            # ✅ [B] 전략 신호 확인
            # ---------------------------------------------------
            simulated_curr = curr.copy()
            if setting['strategy'] == 'SMART_MOMENTUM': simulated_curr['Close'] = curr['High'] 
            signal, reason, _ = get_signal(setting['strategy'], simulated_curr, prev, setting)
            
            action = 'none'
            exec_price = 0
            
            # 매수 로직
            if signal == 'buy':
                if holdings[code] == 0: 
                    if setting['strategy'] == 'SMART_MOMENTUM':
                        k = curr['NoiseMA20'] if not pd.isna(curr['NoiseMA20']) else setting['k']
                        k = max(0.3, min(0.7, k))
                        target_price = curr['Open'] + (curr['Range'] * k)
                        real_buy_price = max(curr['Open'], target_price) # Gap 보정
                        
                        if curr['High'] > target_price:
                            action = 'buy'
                            exec_price = real_buy_price * (1 + SLIPPAGE)
                    else:
                        action = 'buy'
                        exec_price = curr['Close'] * (1 + SLIPPAGE)

            # 매도 로직
            elif holdings[code] > 0:
                sell_signal, sell_reason, _ = get_signal(setting['strategy'], curr, prev, setting)
                if sell_signal == 'sell':
                    action = 'sell'
                    exec_price = curr['Close'] * (1 - SLIPPAGE)
                    reason = sell_reason

            # 주문 집행 및 로그 출력
            if action == 'buy':
                target_amt = current_equity * setting['ratio']
                needed_amt = target_amt - (holdings[code] * exec_price)
                if needed_amt > 0:
                    qty = int(needed_amt / exec_price)
                    if qty > 0 and balance >= qty * exec_price:
                        balance -= qty * exec_price
                        holdings[code] += qty
                        avg_price[code] = exec_price
                        
                        # 🔹 매수 로그 출력
                        print(f"{date_str} | 🔴 매수 | {name:<10} | {exec_price:>8,.0f} | {qty:>5} | {reason}")
                        trade_logs.append({'Date': date_str, 'Type': 'Buy', 'Name': name, 'Price': exec_price, 'Qty': qty, 'Profit': 0, 'Reason': reason})

            elif action == 'sell':
                qty = holdings[code]
                revenue = qty * exec_price
                balance += revenue * (1 - fee)
                holdings[code] = 0
                profit_rate = (exec_price - avg_price[code]) / avg_price[code] * 100
                profit_icon = "📈" if profit_rate > 0 else "📉"
                
                # 🔹 매도 로그 출력
                print(f"{date_str} | 🔵 매도 | {name:<10} | {exec_price:>8,.0f} | {qty:>5} | {profit_icon} {profit_rate:.2f}% ({reason})")
                trade_logs.append({'Date': date_str, 'Type': 'Sell', 'Name': name, 'Price': exec_price, 'Qty': qty, 'Profit': profit_rate, 'Reason': reason})

        daily_history.append(daily_log)

    res_df = pd.DataFrame(daily_history).set_index('Date')
    pd.DataFrame(trade_logs).to_csv('backtest_log.csv', index=False, encoding='utf-8-sig')
    
    final = res_df.iloc[-1]['TotalAsset']
    ret = (final - INIT_BALANCE) / INIT_BALANCE * 100
    mdd = ((res_df['TotalAsset'] - res_df['TotalAsset'].cummax()) / res_df['TotalAsset'].cummax() * 100).min()

    print("\n" + "="*30)
    print(f"💰 최종 자산: {final:,.0f}원")
    print(f"🔥 수익률: {ret:.2f}%")
    print(f"💧 MDD: {mdd:.2f}%")
    print("="*30)
    
    plt.figure(figsize=(10, 5))
    plt.plot(res_df['TotalAsset'], color='red')
    plt.title(f'Backtest Result (Ret: {ret:.2f}%)')
    plt.grid()
    plt.show()

if __name__ == "__main__":
    run()