import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os
import glob
import warnings

# 경고 무시
warnings.filterwarnings('ignore')

# ==========================================
# 1. 전략 함수 정의
# ==========================================

def strat_smart_momentum(curr, prev, setting):
    """
    [전략 1] 스마트 모멘텀 V3 (대형주/ETF용)
    - 매수: 변동성 돌파 + 고점 대비 2% 하락 필터
    - 매도: RSI 85 과열 익절 OR RSI 80+ & 고점대비 -5% 조건부 익절
    """
    # 데이터 검증
    if pd.isna(curr.get('SMA20')) or pd.isna(curr.get('Range')) or pd.isna(curr.get('Open')):
        return 'none', '데이터부족', 0

    # 동적 K (이미 shift된 NoiseMA20 사용)
    if 'NoiseMA20' in curr and not pd.isna(curr['NoiseMA20']):
        k = curr['NoiseMA20']
    else:
        k = setting.get('k', 0.5)
    k = max(0.3, min(0.7, k)) 
    
    # 타겟 가격 (반드시 어제 변동폭 사용!)
    target_price = curr['Open'] + (prev['Range'] * k)
    
    current_price = curr['Close']
    day_high = curr['High'] 
    
    # 매수 조건
    is_bull_market = current_price > curr['SMA20']
    volume_condition = curr['Volume'] > prev['Volume'] * 0.8
    is_breakout = curr['High'] >= target_price # 고가가 타겟을 쳤는가?

    # 필터
    threshold_ratio = 0.98 
    is_near_high = current_price >= (day_high * threshold_ratio)
    is_falling_knife = (day_high > target_price * 1.02) and (current_price < day_high * 0.98)

    # 🟢 [매수 신호]
    if is_breakout and is_bull_market and volume_condition:
        if not is_near_high:
            pct_drop = ((day_high - current_price) / day_high) * 100
            return 'none', f"고점대비하락(-{pct_drop:.1f}%)_매수패스", 0
        if is_falling_knife:
             return 'none', "하락반전_감지_매수패스", 0
        return 'buy', f"스마트_돌파(k={k:.2f})", 0

    # 🔴 [매도 신호]
    current_rsi = curr.get('RSI', 50)
    
    # 1. RSI 과열 익절
    if current_rsi > 85:
        return 'sell', f"RSI초과열({current_rsi:.0f})_익절", 0
    
    # 2. 조건부 트레일링 스탑
    if current_rsi >= 80 and current_price < (day_high * 0.95):
        return 'sell', f"고점(-5%)반납_익절(RSI {current_rsi:.0f})", 0
    
    # 3. 추세 이탈 손절
    sma20_buffer = curr['SMA20'] * 0.99
    if current_price < sma20_buffer:
        return 'sell', "추세이탈(SMA20)_매도", 0
        
    return 'none', '', 0


def get_signal(strategy_name, curr, prev, setting):
    try:
        if strategy_name == "SMART_MOMENTUM":
            return strat_smart_momentum(curr, prev, setting)
        return 'none', '', 0 
    except Exception:
        return 'none', '에러', 0

# ==========================================
# ⚙️ PORTFOLIO 설정 (여기만 수정하세요!)
# ==========================================
PORTFOLIO = {
    # 한국 주식 예시
    #"005930": {"name": "삼성전자", "strategy": "SMART_MOMENTUM", "ratio": 0.2, "k": 0.5},
    #"122630": {"name": "레버리지", "strategy": "SMART_MOMENTUM", "ratio": 0.3, "k": 0.4},
    #"252670": {"name": "인버스2X", "strategy": "SMART_MOMENTUM", "ratio": 0.1, "k": 0.4},
    
    # 중소형주 (전략명 주의: SMART_MOMENTUM 사용)
    #"107640": {"name": "한중엔시에스", "strategy": "SMART_MOMENTUM", "ratio": 0.2, "k": 0.6},
    #"017960": {"name": "한국카본", "strategy": "SMART_MOMENTUM", "ratio": 0.2, "k": 0.6},

    # 미국 주식 예시 (미국 데이터 수집 후 사용 가능)
    "TQQQ": {"name": "나스닥3배", "strategy": "SMART_MOMENTUM", "ratio": 0.3, "k": 0.5},
    "SQQQ": {"name": "나스닥3배_인버스", "strategy": "SMART_MOMENTUM", "ratio": 0.1, "k": 0.5},
    "SOXL": {"name": "반도체3배", "strategy": "SMART_MOMENTUM", "ratio": 0.2, "k": 0.5},
    "SOXS": {"name": "반도체3배", "strategy": "SMART_MOMENTUM", "ratio": 0.1, "k": 0.5},
    "TSLA": {"name": "테슬라", "strategy": "SMART_MOMENTUM", "ratio": 0.2, "k": 0.5},
    "GOOG": {"name": "구글", "strategy": "SMART_MOMENTUM", "ratio": 0.2, "k": 0.5},
}

INIT_BALANCE = 10000000  
COMMISSION = 0.002 # 수수료+슬리피지 통합 0.2%

# ==========================================
# 🧠 지표 계산
# ==========================================
def calculate_indicators(df):
    df = df.copy()
    
    # SMA
    df['SMA20'] = df['Close'].rolling(window=20).mean()
    
    # RSI
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # Range & Noise
    df['Range'] = df['High'] - df['Low']
    range_k = df['Range'].replace(0, 1)
    df['Noise'] = 1 - (abs(df['Open'] - df['Close']) / range_k)
    
    # 🚨 [중요] NoiseMA20은 '어제'까지의 데이터를 써야 하므로 shift(1) 필수
    df['NoiseMA20'] = df['Noise'].rolling(window=20).mean().shift(1)
    
    # A/D Line
    high_low = df['High'] - df['Low']
    high_low = high_low.replace(0, 1)
    clv = ((df['Close'] - df['Low']) - (df['High'] - df['Close'])) / high_low
    clv = clv.fillna(0)
    df['AD'] = (clv * df['Volume']).cumsum()
    df['AD_MA20'] = df['AD'].rolling(window=20).mean()
    
    return df

# ==========================================
# 🚀 백테스트 실행 엔진
# ==========================================
def run():
    files = glob.glob("history_data_backtest/*.csv")
    if not files: 
        print("❌ 'history_data_backtest' 폴더에 csv 파일이 없습니다.")
        return

    data_map = {}
    print(f"🔄 데이터 로딩 중... ({len(files)}개 파일)")
    
    for f in files:
        # 파일명에서 종목코드 추출 (한국:005930, 미국:TQQQ)
        code = os.path.basename(f).split('.')[0]
        if code not in PORTFOLIO: continue
        try:
            df = pd.read_csv(f, parse_dates=['Date'], index_col='Date')
            df.sort_index(inplace=True) # 날짜 정렬 보장
            if len(df) < 60: continue
            df = calculate_indicators(df)
            data_map[code] = df
        except Exception as e:
            print(f"⚠️ {code} 로드 실패: {e}")

    if not data_map: 
        print("❌ 유효한 데이터가 없습니다. PORTFOLIO 설정을 확인하세요.")
        return

    # 공통 날짜 인덱스 생성
    all_dates = sorted(list(set.union(*[set(df.index) for df in data_map.values()])))
    balance = INIT_BALANCE
    holdings = {code: 0 for code in PORTFOLIO}
    avg_price = {code: 0 for code in PORTFOLIO}
    
    daily_history = []
    trade_logs = [] 

    print(f"\n🚀 백테스트 시작! ({all_dates[0].date()} ~ {all_dates[-1].date()})")
    print("-" * 100)
    print(f"{'날짜':<12} | {'유형':<4} | {'종목명':<10} | {'체결가':>9} | {'수익률/이유'}")
    print("-" * 100)
    
    for i in range(1, len(all_dates)):
        today = all_dates[i]
        prev_day = all_dates[i-1]
        date_str = today.strftime('%Y-%m-%d')
        
        current_equity = balance
        for code, qty in holdings.items():
            if qty > 0:
                price = data_map[code].loc[today]['Close'] if today in data_map[code].index else 0
                if price > 0: current_equity += qty * price
        
        daily_log = {'Date': today, 'TotalAsset': current_equity}
        
        for code, setting in PORTFOLIO.items():
            if code not in data_map: continue
            df = data_map[code]
            if today not in df.index or prev_day not in df.index: continue
            
            curr = df.loc[today]
            prev = df.loc[prev_day]
            name = setting['name']
            
            # ----------------------------------------
            # [A] 매도 (Sell)
            # ----------------------------------------
            if holdings[code] > 0:
                action = 'none'
                sell_reason = ''
                exec_price = 0

                # 전략별 매도 로직
                if setting['strategy'] == 'SMART_AD_MOMENTUM':
                    # A/D 전략은 무조건 시가 청산 (Overnight)
                    action = 'sell'
                    sell_reason = '시가청산(Overnight)'
                    exec_price = curr['Open']
                else:
                    # 일반 전략은 신호 대기
                    signal, reason, _ = get_signal(setting['strategy'], curr, prev, setting)
                    if signal == 'sell':
                        action = 'sell'
                        sell_reason = reason
                        exec_price = curr['Close']

                if action == 'sell':
                    qty = holdings[code]
                    amount = qty * exec_price
                    balance += amount * (1 - COMMISSION)
                    
                    profit_rate = (exec_price - avg_price[code]) / avg_price[code] * 100
                    icon = "📈" if profit_rate > 0 else "📉"
                    
                    print(f"{date_str} | 🔵 매도 | {name:<10} | {exec_price:>9,.0f} | {icon} {profit_rate:.2f}% ({sell_reason})")
                    trade_logs.append({'Date': date_str, 'Name': name, 'Type': 'Sell', 'Price': exec_price, 'Profit': profit_rate, 'Reason': sell_reason})
                    
                    holdings[code] = 0
                    avg_price[code] = 0

            # ----------------------------------------
            # [B] 매수 (Buy)
            # ----------------------------------------
            elif holdings[code] == 0:
                signal, reason, _ = get_signal(setting['strategy'], curr, prev, setting)
                
                if signal == 'buy':
                    target_ratio = setting['ratio']
                    invest_amt = current_equity * target_ratio
                    
                    if balance > invest_amt:
                        # 🚨 [중요] 목표가 계산 시 반드시 prev['Range'] 사용
                        k = curr['NoiseMA20'] if not pd.isna(curr.get('NoiseMA20')) else setting.get('k', 0.5)
                        target_p = curr['Open'] + (prev['Range'] * k)
                        
                        # 시가가 이미 목표가보다 높으면 시가 체결, 아니면 목표가 체결
                        buy_price = max(curr['Open'], target_p)
                        
                        qty = int(invest_amt / buy_price)
                        if qty > 0:
                            cost = qty * buy_price
                            balance -= cost * (1 + COMMISSION)
                            holdings[code] = qty
                            avg_price[code] = buy_price
                            
                            print(f"{date_str} | 🔴 매수 | {name:<10} | {buy_price:>9,.0f} | {reason}")
                            trade_logs.append({'Date': date_str, 'Name': name, 'Type': 'Buy', 'Price': buy_price, 'Profit': 0, 'Reason': reason})

        daily_history.append(daily_log)

    # 결과 출력
    res_df = pd.DataFrame(daily_history).set_index('Date')
    final = res_df.iloc[-1]['TotalAsset']
    ret = (final - INIT_BALANCE) / INIT_BALANCE * 100
    res_df['Peak'] = res_df['TotalAsset'].cummax()
    mdd = ((res_df['TotalAsset'] - res_df['Peak']) / res_df['Peak'] * 100).min()

    print("\n" + "="*40)
    print(f"💰 최종 자산: {final:,.0f}원")
    print(f"🔥 총 수익률: {ret:.2f}%")
    print(f"💧 MDD: {mdd:.2f}%")
    print("="*40)
    
    plt.figure(figsize=(12, 6))
    plt.plot(res_df['TotalAsset'], color='red', label='Total Asset')
    plt.title(f'Backtest Result (Ret: {ret:.2f}%, MDD: {mdd:.2f}%)')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.show()

if __name__ == "__main__":
    run()