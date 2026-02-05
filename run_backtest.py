import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os
import glob
import warnings
import platform

# 경고 무시 및 폰트 설정
warnings.filterwarnings('ignore')
plt.rcParams['axes.unicode_minus'] = False

system_name = platform.system()

if system_name == 'Darwin': # Mac 환경
    plt.rc('font', family='AppleGothic')
elif system_name == 'Windows': # Windows 환경
    plt.rc('font', family='Malgun Gothic')
else: # Linux 환경 (구글 코랩 등)
    plt.rc('font', family='NanumGothic')

# 마이너스(-) 부호가 깨지는 현상 방지
plt.rcParams['axes.unicode_minus'] = False

# ==========================================
# 1. 전략 함수 정의 (SMART_PRO)
# ==========================================

def strat_smart_momentum_pro(curr, prev, setting):
    """
    [전략] 스마트 모멘텀 PRO
    """
    # 0. 레벨 파싱 (여기서 setting은 {'level': N} 딕셔너리임)
    level = setting.get('level', 2)
    
    # [티어별 스탯 설정]
    if level == 5: # 🐲 드래곤 (3배 ETF)
        gap_trigger = 0.01; k_discount = 5.0; vol_ratio = 0.3
        drop_base = 0.90; drop_tight = 0.95; rsi_hot = 90
    elif level == 4: # 🥷 어쌔신 (로봇/바이오)
        gap_trigger = 0.02; k_discount = 3.0; vol_ratio = 0.5
        drop_base = 0.93; drop_tight = 0.96; rsi_hot = 85
    elif level == 3: # 🏹 헌터 (2배/테슬라)
        gap_trigger = 0.02; k_discount = 2.0; vol_ratio = 0.6
        drop_base = 0.94; drop_tight = 0.97; rsi_hot = 80
    elif level == 1: # 🛡️ 탱커 (삼성전자)
        gap_trigger = 0.05; k_discount = 1.0; vol_ratio = 1.0
        drop_base = 0.97; drop_tight = 0.985; rsi_hot = 75
    else: # ⚔️ 전사 (Lv 2)
        gap_trigger = 0.03; k_discount = 1.5; vol_ratio = 0.8
        drop_base = 0.95; drop_tight = 0.97; rsi_hot = 80

    # 🛡️ [방어] 갭하락 출발 금지
    gap_start = (curr['Open'] - prev['Close']) / prev['Close']
    if gap_start < -0.02:
        if level < 5: return 'none', f"갭하락({gap_start*100:.1f}%)_Pass", 0
        elif gap_start < -0.04: return 'none', f"폭락출발({gap_start*100:.1f}%)_Pass", 0
        
    # 🛡️ [방어] 20일선 우하향 금지
    sma20_slope = curr['SMA20'] - prev['SMA20']
    if sma20_slope < 0 and level < 4:
        return 'none', "20일선_우하향_Pass", 0

    # 🔴 [매도] 가변형 트레일링 스탑
    current_price = curr['Close']
    recent_high = curr['High5'] if 'High5' in curr else curr['High']
    current_rsi = curr.get('RSI', 50)
    
    if current_rsi >= rsi_hot:
        limit_price = recent_high * drop_tight
        msg_type = f"과열권_조정(-{(1-drop_tight)*100:.1f}%)"
    else:
        limit_price = recent_high * drop_base
        msg_type = f"고점대비하락(-{(1-drop_base)*100:.1f}%)"
        
    if current_price < limit_price:
        return 'sell', f"{msg_type}_청산", 0
        
    if current_price < curr['SMA20'] * 0.99:
        return 'sell', "추세이탈(SMA20)", 0

    # 🟢 [매수] 
    k = curr.get('NoiseMA20', 0.5)
    if pd.isna(k): k = 0.5
    
    # 갭상승 K 할인 적용
    if gap_start >= gap_trigger:
        k = max(0.3, k - (gap_start * k_discount))
    k = max(0.3, min(0.7, k))

    target_price = curr['Open'] + (prev['Range'] * k)
    
    is_bull = current_price > curr['SMA20']
    is_breakout = current_price > target_price
    is_vol_ok = curr['Volume'] > prev['Volume'] * vol_ratio
    
    if is_breakout and is_bull and is_vol_ok:
        return 'buy', f"PRO_돌파(Lv.{level}, k={k:.2f})", 0

    return 'none', '', 0

def get_signal(strategy_name, curr, prev, setting):
    if strategy_name == "SMART_PRO":
        return strat_smart_momentum_pro(curr, prev, setting)
    return 'none', '', 0

# ==========================================
# ⚙️ PORTFOLIO 설정 (전략명 'SMART_PRO'로 통일!)
# ==========================================
PORTFOLIO = {
    # 🦁 [Lv 5] 야수형 (3배 레버리지)
        # 특징: 갭상승 1%면 바로 탑승 / -10%까지 버팀 / 거래량 30%면 OK
    # 🥷 [Lv 4] 어쌔신 (중소형 로봇주)
        # 특징: 갭상승 2%면 탑승 / -7% 버팀 / 위아래 흔들기 심함
    # 🏹 [Lv 3] 헌터형 (성장주)
        # 특징: 갭상승 2%면 탑승 / -6%까지 버팀 / 거래량 60% 확인
    # ⚔️ [Lv 2] 전사형 (빅테크 우량주)
        # 특징: 갭상승 3%면 탑승 / -5% 국룰 손절 / 거래량 80% 확인

    # 🇰🇷 [한국]
    #"005930": {"name": "삼성전자", "strategy": "SMART_PRO", "ratio": 0.15, "setting": {"level": 3}},
    #"000660": {"name": "SK하이닉스", "strategy": "SMART_PRO", "ratio": 0.10, "setting": {"level": 3}},
    #"196170": {"name": "알테오젠", "strategy": "SMART_PRO", "ratio": 0.05, "setting": {"level": 4}},
    #"012450": {"name": "한화에어로", "strategy": "SMART_PRO", "ratio": 0.05, "setting": {"level": 4}}, # 테스트 위해 비중 0.05 부여
    #"122630": {"name": "KODEX레버", "strategy": "SMART_PRO", "ratio": 0.30, "setting": {"level": 3}},

    # 로봇 군단
    #"005380": {"name": "현대차", "strategy": "SMART_PRO", "ratio": 0.10, "setting": {"level": 3}},
    #"058610": {"name": "에스피지", "strategy": "SMART_PRO", "ratio": 0.10, "setting": {"level": 4}},
    #"454910": {"name": "두산로보", "strategy": "SMART_PRO", "ratio": 0.05, "setting": {"level": 4}},
    #"277810": {"name": "레인보우", "strategy": "SMART_PRO", "ratio": 0.05, "setting": {"level": 4}},
    "107640": {"name": "한중엔시에스(ESS저장장치)", "strategy": "SMART_PRO", "ratio": 0.50, "setting": {"level": 2}},
    "373220": {"name": "LG에너지솔루션", "strategy": "SMART_PRO", "ratio": 0.50, "setting": {"level": 3}},

    # ------------------------------------------------
    # 🇺🇸 [USA] 미국 주식 백테스트
    # ------------------------------------------------
    #"SOXL": {"name": "반도체3배", "strategy": "SMART_PRO", "ratio": 0.2, "setting": {"level": 4}},
    #"TQQQ": {"name": "나스닥3배", "strategy": "SMART_PRO", "ratio": 0.2, "setting": {"level": 4}}, # (테스트용 비중 0)
    #"SQQQ": {"name": "나스닥3배_인버스", "strategy": "SMART_PRO", "ratio": 0.05, "setting": {"level": 5}},
    #"SOXS": {"name": "반도체3배_인버스", "strategy": "SMART_PRO", "ratio": 0.05,"setting": {"level": 5}},
    #"TSLA": {"name": "테슬라", "strategy": "SMART_PRO", "ratio": 0.2, "setting": {"level": 3}},
    #"ISRG": {"name": "인튜이티브", "strategy": "SMART_PRO", "ratio": 0.1, "setting": {"level": 3}},
    #"GOOG": {"name": "구글", "strategy": "SMART_PRO", "ratio": 0.0, "setting": {"level": 3}},
    #"AMZN": {"name": "아마존", "strategy": "SMART_PRO", "ratio": 0.0, "setting": {"level": 3}},
    #"SYM":  {"name": "심보틱", "strategy": "SMART_PRO", "ratio": 0.1, "setting": {"level": 4}},

    

}

INIT_BALANCE = 10000000  
COMMISSION = 0.002 

# ==========================================
# 🧠 지표 계산
# ==========================================
def calculate_indicators(df):
    """
    보조지표 계산 (SMA, RSI, 노이즈, +High5)
    """
    # 데이터가 너무 적으면 계산 불가
    if len(df) < 20: return pd.DataFrame()
    
    df = df.copy()
    
    # 1. 이동평균선 (SMA)
    df['SMA5'] = df['Close'].rolling(window=5).mean()
    df['SMA20'] = df['Close'].rolling(window=20).mean()
    df['SMA60'] = df['Close'].rolling(window=60).mean()
    
    # 2. 노이즈 (동적 K용)
    range_size = df['High'] - df['Low']
    body_size = (df['Open'] - df['Close']).abs()
    noise = 1 - (body_size / range_size.replace(0, 1))
    df['NoiseMA20'] = noise.rolling(window=20).mean() # 최근 20일 평균 노이즈

    # 3. 변동성 (Range)
    df['Range'] = df['High'].shift(1) - df['Low'].shift(1)

    # 4. RSI (14일)
    delta = df['Close'].diff(1)
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    rs = gain.rolling(window=14).mean() / loss.rolling(window=14).mean().replace(0, 1)
    df['RSI'] = 100 - (100 / (1 + rs))

    # 5. 거래량 이평
    df['VolMA5'] = df['Volume'].rolling(window=5).mean()

    # ✅ [NEW] 최근 5일간 최고가 (High5) - 가변형 익절 기준
    # 오늘 포함 과거 5일 중 최고가
    df['High5'] = df['High'].rolling(window=5).max()
    df['High5'].fillna(df['High'], inplace=True) # 앞부분 NaN 방지

    # NaN 제거
    df.dropna(inplace=True)
    
    # 🚨 [수정] reset_index를 하지 말고 그대로 리턴해야 날짜 인덱스가 유지됨!
    return df

# ==========================================
# 🚀 백테스트 실행 엔진 (수정완료)
# ==========================================
def run():
    # 폴더 확인 및 생성
    if not os.path.exists("history_data_backtest"):
        os.makedirs("history_data_backtest")
        print("📁 'history_data_backtest' 폴더를 생성했습니다. 여기에 CSV 파일을 넣어주세요.")
        return

    files = glob.glob("history_data_backtest/*.csv")
    if not files: 
        print("❌ 'history_data_backtest' 폴더에 csv 파일이 없습니다. 파일을 넣고 다시 실행하세요.")
        return

    data_map = {}
    print(f"🔄 데이터 로딩 중... ({len(files)}개 파일)")
    
    for f in files:
        code = os.path.basename(f).split('.')[0]
        if code not in PORTFOLIO: continue
        try:
            df = pd.read_csv(f, parse_dates=['Date'], index_col='Date')
            df.sort_index(inplace=True) 
            if len(df) < 60: continue
            df = calculate_indicators(df)
            data_map[code] = df
        except Exception as e:
            print(f"⚠️ {code} 로드 실패: {e}")

    if not data_map: 
        print("❌ 유효한 데이터가 없습니다. PORTFOLIO 설정을 확인하세요.")
        return

    all_dates = sorted(list(set.union(*[set(df.index) for df in data_map.values()])))
    balance = INIT_BALANCE
    holdings = {code: 0 for code in PORTFOLIO}
    avg_price = {code: 0 for code in PORTFOLIO}
    
    daily_history = []
    trade_logs = [] 

    print(f"\n🚀 백테스트 시작! (전략: SMART_PRO)")
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
        
        for code, config in PORTFOLIO.items():
            if code not in data_map: continue
            df = data_map[code]
            if today not in df.index or prev_day not in df.index: continue
            
            curr = df.loc[today]
            prev = df.loc[prev_day]
            name = config['name']
            
            # 🚨 [핵심] get_signal에 setting 전체가 아니라 'config['setting']'을 넘겨야 함!
            level_setting = config.get('setting', {'level': 2}) 
            
            # ----------------------------------------
            # [A] 매도 (Sell)
            # ----------------------------------------
            if holdings[code] > 0:
                signal, reason, _ = get_signal(config['strategy'], curr, prev, level_setting)
                
                if signal == 'sell':
                    exec_price = curr['Close']
                    qty = holdings[code]
                    amount = qty * exec_price
                    balance += amount * (1 - COMMISSION)
                    
                    profit_rate = (exec_price - avg_price[code]) / avg_price[code] * 100
                    icon = "📈" if profit_rate > 0 else "📉"
                    
                    print(f"{date_str} | 🔵 매도 | {name:<10} | {exec_price:>9,.0f} | {icon} {profit_rate:.2f}% ({reason})")
                    trade_logs.append({'Date': date_str, 'Name': name, 'Type': 'Sell', 'Price': exec_price, 'Profit': profit_rate, 'Reason': reason})
                    
                    holdings[code] = 0
                    avg_price[code] = 0

            # ----------------------------------------
            # [B] 매수 (Buy)
            # ----------------------------------------
            elif holdings[code] == 0:
                signal, reason, _ = get_signal(config['strategy'], curr, prev, level_setting)
                
                if signal == 'buy':
                    target_ratio = config['ratio']
                    invest_amt = current_equity * target_ratio
                    
                    if balance > invest_amt and invest_amt > 10000:
                        # 🚨 [중요] 백테스트 엔진에서도 '갭 보정된 K'를 다시 계산해야 정확한 매수가가 나옴
                        k = curr['NoiseMA20'] if not pd.isna(curr.get('NoiseMA20')) else 0.5
                        
                        # (1) 레벨 가져오기
                        level = level_setting.get('level', 2)
                        
                        # (2) 파라미터 세팅 (전략과 동일하게!)
                        if level == 5:   gap_trigger=0.01; k_discount=5.0
                        elif level == 4: gap_trigger=0.02; k_discount=3.0
                        elif level == 3: gap_trigger=0.02; k_discount=2.0
                        elif level == 1: gap_trigger=0.05; k_discount=1.0
                        else:            gap_trigger=0.03; k_discount=1.5
                        
                        # (3) 갭 보정 적용
                        gap_start = (curr['Open'] - prev['Close']) / prev['Close']
                        if gap_start >= gap_trigger:
                            k = max(0.3, k - (gap_start * k_discount))
                        k = max(0.3, min(0.7, k))
                        
                        # (4) 최종 목표가 계산
                        target_p = curr['Open'] + (prev['Range'] * k)
                        buy_price = max(curr['Open'], target_p) # 시가가 목표가보다 높으면 시가 체결
                        
                        qty = int(invest_amt / buy_price)
                        if qty > 0:
                            cost = qty * buy_price
                            balance -= cost * (1 + COMMISSION)
                            holdings[code] = qty
                            avg_price[code] = buy_price
                            
                            print(f"{date_str} | 🔴 매수 | {name:<10} | {buy_price:>9,.0f} | {reason}")
                            trade_logs.append({'Date': date_str, 'Name': name, 'Type': 'Buy', 'Price': buy_price, 'Profit': 0, 'Reason': reason})

        daily_history.append(daily_log)

    if not daily_history:
        print("❌ 거래 내역이 없습니다.")
        return

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
    plt.title(f'Smart Momentum PRO Backtest (Ret: {ret:.2f}%, MDD: {mdd:.2f}%)')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.show()

if __name__ == "__main__":
    run()