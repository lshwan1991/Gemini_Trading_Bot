import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os
import glob

# ==========================================
# 1. 전략 함수 정의 (최종 튜닝 버전)
# ==========================================

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

def strat_smart_ad_momentum(curr, prev, setting):
    """[중소형주] 스마트 모멘텀 + A/D(세력수급) 필터"""
    if pd.isna(curr.get('AD')) or pd.isna(curr.get('AD_MA20')): return 'none', '', 0
    
    # 1. 기존 스마트 모멘텀 로직 가져오기
    signal, reason, _ = strat_smart_momentum(curr, prev, setting)
    
    # 2. 매수 신호일 때만 A/D 필터 체크
    if signal == 'buy':
        # A/D Line이 20일 평균보다 위에 있어야 함 (자금 유입 확인)
        if curr['AD'] > curr['AD_MA20']:
            return 'buy', reason + "+AD수급", 0
        else:
            return 'none', '', 0 # 돌파는 했으나 수급이 구려서 패스
            
    return signal, reason, 0 # 매도 신호는 그대로 통과

def get_signal(strategy_name, curr, prev, setting):
    try:
        if strategy_name == "SMART_MOMENTUM":
            return strat_smart_momentum(curr, prev, setting)
        # ✅ 신규 전략 추가
        if strategy_name == "SMART_AD_MOMENTUM":
            return strat_smart_ad_momentum(curr, prev, setting)
            
        return 'none', '', 0 
    except Exception as e:
        # print(f"⚠️ 전략 에러: {e}")
        return 'none', '에러발생', 0

# ==========================================
# ⚙️ 설정: 5차 테스트 비율 (2:2:2:2:2)
# ==========================================
PORTFOLIO = {
    # [대형주: MACD_RSI_OPTIMIZED]
    "005930": {"name": "삼성전자", "strategy": "SMART_MOMENTUM", "ratio": 0.2, "k": 0.5},
    
    # [ETF: SMART_MOMENTUM]
    "252670": {"name": "인버스2X", "strategy": "SMART_MOMENTUM", "ratio": 0.10, "k": 0.4},
    "122630": {"name": "레버리지", "strategy": "SMART_MOMENTUM", "ratio": 0.20, "k": 0.4},
    
    # [중소형주: SMART_MOMENTUM]
    "107640": {"name": "한중엔시에스", "strategy": "LW_AD_HYBRID", "ratio": 0.3, "k": 0.6},
    "017960": {"name": "한국카본", "strategy": "LW_AD_HYBRID", "ratio": 0.2, "k": 0.6},
}

INIT_BALANCE = 10000000  
COMMISSION_ETF = 0.00015 
COMMISSION_STK = 0.0023  
SLIPPAGE = 0.002 

# ==========================================
# 🧠 지표 계산 및 백테스트 엔진
# ==========================================
def calculate_indicators(df):
    # 기존 지표
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
    
    # ✅ [신규] A/D Line (매집/분산) 계산
    # CLV = {(Close-Low) - (High-Close)} / (High-Low)
    # AD = cumsum(CLV * Volume)
    high_low = df['High'] - df['Low']
    high_low = high_low.replace(0, 1) # 0으로 나누기 방지
    clv = ((df['Close'] - df['Low']) - (df['High'] - df['Close'])) / high_low
    df['AD'] = (clv * df['Volume']).cumsum()
    
    # A/D의 추세를 보기 위한 20일 이평선
    df['AD_MA20'] = df['AD'].rolling(window=20).mean()
    
    return df

def run():
    files = glob.glob("history_data_backtest/*.csv")
    if not files: 
        print("❌ history_data_backtest 폴더에 csv 파일이 없습니다.")
        return

    data_map = {}
    print(f"🔄 데이터 로딩 및 지표 계산 중... ({len(files)}개)")
    for f in files:
        code = os.path.basename(f).replace('.csv', '')
        if code not in PORTFOLIO: continue
        try:
            df = pd.read_csv(f, parse_dates=['Date'], index_col='Date')
            # 결측치나 데이터가 너무 적으면 패스
            if len(df) < 60: continue
            df = calculate_indicators(df)
            data_map[code] = df
        except Exception as e:
            print(f"Error loading {code}: {e}")

    if not data_map: 
        print("❌ 유효한 데이터가 없습니다.")
        return

    all_dates = sorted(list(set.union(*[set(df.index) for df in data_map.values()])))
    balance = INIT_BALANCE
    holdings = {code: 0 for code in PORTFOLIO}
    avg_price = {code: 0 for code in PORTFOLIO}
    daily_history = []
    trade_logs = [] 

    print(f"🚀 백테스트 시작! (기간: {all_dates[0].date()} ~ {all_dates[-1].date()})")
    print("-" * 100)
    print(f"{'날짜':<12} | {'유형':<4} | {'종목명':<10} | {'체결가':>8} | {'수량':>5} | {'수익률/이유':<20}")
    print("-" * 100)
    
    for i in range(1, len(all_dates)):
        today = all_dates[i]
        prev_day = all_dates[i-1]
        date_str = today.strftime('%Y-%m-%d')
        
        # 1. 자산 평가 (종가 기준)
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
            
            # 리밸런싱 및 전략 공통 변수
            name = setting['name']
            is_etf = "KODEX" in name or "ETF" in name
            fee = COMMISSION_ETF if is_etf else COMMISSION_STK
            
            # ---------------------------------------------------
            # ✅ [A] 매도 (Sell) 먼저 처리
            # ---------------------------------------------------
            if holdings[code] > 0:
                action = 'none'
                sell_reason = ''
                exec_price = 0

                # 1. LW_AD_HYBRID 전략의 '시가 청산' 로직 (Overnight)
                # 어제 샀으면 오늘 시가에 무조건 팝니다.
                if setting['strategy'] == 'LW_AD_HYBRID':
                    action = 'sell'
                    sell_reason = '시가청산(Overnight)'
                    exec_price = curr['Open'] # 시가 매도!
                
                # 2. 다른 전략들은 시그널 확인 후 매도
                else:
                    signal, reason, _ = get_signal(setting['strategy'], curr, prev, setting)
                    if signal == 'sell':
                        action = 'sell'
                        sell_reason = reason
                        exec_price = curr['Close'] * (1 - SLIPPAGE) # 종가 매도

                # 매도 실행
                if action == 'sell':
                    qty = holdings[code]
                    revenue = qty * exec_price
                    balance += revenue * (1 - fee)
                    
                    profit_rate = (exec_price - avg_price[code]) / avg_price[code] * 100
                    holdings[code] = 0
                    
                    profit_icon = "📈" if profit_rate > 0 else "📉"
                    print(f"{date_str} | 🔵 매도 | {name:<10} | {exec_price:>8,.0f} | {qty:>5} | {profit_icon} {profit_rate:.2f}% ({sell_reason})")
                    trade_logs.append({'Date': date_str, 'Type': 'Sell', 'Name': name, 'Price': exec_price, 'Qty': qty, 'Profit': profit_rate, 'Reason': sell_reason})
                    
                    # 매도 후 현금 증가분 반영
                    current_equity = balance + sum(holdings[c] * data_map[c].loc[today]['Close'] for c in holdings if holdings[c] > 0)

            # ---------------------------------------------------
            # ✅ [B] 매수 (Buy) 처리
            # ---------------------------------------------------
            signal, reason, _ = get_signal(setting['strategy'], curr, prev, setting)
            
            if signal == 'buy' and holdings[code] == 0:
                target_ratio = setting['ratio']
                target_amt = current_equity * target_ratio
                
                # 이미 보유한 종목 제외 가용 현금 내에서 매수
                if balance > target_amt:
                    buy_price = 0
                    
                    # 변동성 돌파류 전략은 목표가(Target Price)로 체결 가정
                    if setting['strategy'] in ['SMART_MOMENTUM', 'LW_AD_HYBRID']:
                        k = curr['NoiseMA20'] if 'NoiseMA20' in curr else setting.get('k', 0.6)
                        if setting['strategy'] == 'LW_AD_HYBRID': k = setting.get('k', 0.6)
                        
                        target_p = curr['Open'] + (curr['Range'] * k)
                        # 시가가 이미 목표가보다 높으면 시가 체결, 아니면 목표가 체결
                        buy_price = max(curr['Open'], target_p) * (1 + SLIPPAGE)
                    else:
                        buy_price = curr['Close'] * (1 + SLIPPAGE)

                    qty = int(target_amt / buy_price)
                    
                    if qty > 0 and balance >= qty * buy_price:
                        balance -= qty * buy_price
                        holdings[code] += qty
                        avg_price[code] = buy_price
                        
                        print(f"{date_str} | 🔴 매수 | {name:<10} | {buy_price:>8,.0f} | {qty:>5} | {reason}")
                        trade_logs.append({'Date': date_str, 'Type': 'Buy', 'Name': name, 'Price': buy_price, 'Qty': qty, 'Profit': 0, 'Reason': reason})

        daily_history.append(daily_log)

    # ==========================================
    # 📊 결과 분석
    # ==========================================
    if not daily_history:
        print("결과가 없습니다.")
        return

    res_df = pd.DataFrame(daily_history).set_index('Date')
    pd.DataFrame(trade_logs).to_csv('backtest_log.csv', index=False, encoding='utf-8-sig')
    
    final = res_df.iloc[-1]['TotalAsset']
    ret = (final - INIT_BALANCE) / INIT_BALANCE * 100
    mdd = ((res_df['TotalAsset'] - res_df['TotalAsset'].cummax()) / res_df['TotalAsset'].cummax() * 100).min()

    print("\n" + "="*40)
    print(f"💰 초기 자본: {INIT_BALANCE:,.0f}원")
    print(f"💰 최종 자산: {final:,.0f}원")
    print(f"🔥 총 수익률: {ret:.2f}%")
    print(f"💧 MDD (최대낙폭): {mdd:.2f}%")
    print("="*40)
    
    plt.figure(figsize=(12, 6))
    plt.plot(res_df['TotalAsset'], label='Total Asset', color='red')
    plt.title(f'Backtest Result (Ret: {ret:.2f}%, MDD: {mdd:.2f}%)')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.show()

if __name__ == "__main__":
    run()