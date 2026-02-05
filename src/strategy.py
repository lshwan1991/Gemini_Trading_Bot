import pandas as pd
from datetime import datetime
import pytz
import numpy as np

def strat_macd_rsi(curr, prev, setting):
    """
    [전략] MACD + RSI
    :return: (신호, 사유, 더미수량)
    """
    rsi_buy = setting.get('rsi_buy', 30)
    rsi_sell = setting.get('rsi_sell', 70)
    
    # 매수 조건: MACD 골든크로스 AND RSI 건전
    # (curr는 오늘, prev는 어제 데이터)
    if prev['MACD'] < prev['Signal'] and curr['MACD'] > curr['Signal'] and curr['RSI'] < 70:
        return 'buy', "MACD_골든크로스", 0
    
    # 매도 조건: MACD 데드크로스 OR RSI 과열
    if (prev['MACD'] > prev['Signal'] and curr['MACD'] < curr['Signal']) or curr['RSI'] > rsi_sell:
        reason = "RSI과열" if curr['RSI'] > rsi_sell else "MACD_데드크로스"
        return 'sell', reason, 0
        
    return 'none', '', 0

def strat_macd_rsi_optimized(curr, prev, setting):
    """
    [전략] MACD + RSI + 이동평균선 필터 (대형주 전용)
    - 60일 이평선 위에 있을 때만 MACD 골든크로스 진입
    - 승률을 높이고 잦은 매매를 줄임
    """
    # 데이터가 60일치도 안되면 계산 불가
    if pd.isna(curr.get('SMA60')):
        return 'none', 'SMA60_데이터부족', 0

    rsi_buy = setting.get('rsi_buy', 40)  # 대형주는 30까지 잘 안 내려옴, 40으로 상향 추천
    rsi_sell = setting.get('rsi_sell', 70)
    
    # [지표 정의]
    is_golden_cross = (prev['MACD'] < prev['Signal']) and (curr['MACD'] > curr['Signal'])
    is_dead_cross = (prev['MACD'] > prev['Signal']) and (curr['MACD'] < curr['Signal'])
    
    # [필터] 추세 확인 (현재가가 60일선보다 위에 있는가?)
    is_uptrend = curr['Close'] > curr['SMA60']
    
    # ---------------------------------------------------
    # 🚀 [매수] MACD 골든크로스 + RSI 건전 + 60일선 위(상승장)
    # ---------------------------------------------------
    if is_golden_cross and curr['RSI'] < 70 and is_uptrend:
        return 'buy', "MACD_골든크로스(추세장)", 0

    # ---------------------------------------------------
    # 💧 [매도] MACD 데드크로스 OR RSI 과열 OR 추세 붕괴
    # ---------------------------------------------------
    # 1. RSI가 너무 높으면 익절
    if curr['RSI'] > rsi_sell:
        return 'sell', "RSI_과열_익절", 0
        
    # 2. MACD가 꺾이면 매도 (가장 기본)
    if is_dead_cross:
        return 'sell', "MACD_데드크로스", 0
        
    # 3. [손절/익절] 주가가 60일선 아래로 붕괴되면 탈출 (대형주 생명선)
    if curr['Close'] < curr['SMA60']:
        return 'sell', "추세이탈(SMA60)_매도", 0

    return 'none', '', 0

def strat_volatility_breakout(curr, prev, setting):
    """
    [전략] 변동성 돌파 (한국 테마 및 주도주)
    """
    k = setting.get('k', 0.6)
    
    # 목표가 계산: 오늘 시가 + (어제 변동폭 * k)
    target_price = curr['Open'] + (curr['Range'] * k)
    current_price = curr['Close']

    # 매수: 현재가가 목표가를 돌파했을 때
    if current_price > target_price:
        return 'buy', "변동성돌파_성공", 0
        
    # 매도: 시가 아래로 떨어지면 손절 (혹은 장 마감 시 매도 로직은 Trader에서 처리)
    if current_price < curr['Open']:
        return 'sell', "시가이탈_손절", 0
        
    return 'none', '', 0

def strat_smart_momentum(curr, prev, setting):
    """
    [전략] 스마트 모멘텀 (Final: 추세 추종 강화 + 휩소 방어)
    """
    # 0. 데이터 검증
    if pd.isna(curr['SMA20']) or pd.isna(curr['Range']) or pd.isna(curr['Open']):
        return 'none', '데이터부족', 0

    # 1. 동적 K (노이즈 필터)
    if 'NoiseMA20' in curr and not pd.isna(curr['NoiseMA20']):
        k = curr['NoiseMA20']
    else:
        k = setting.get('k', 0.5)
        
    k = max(0.3, min(0.7, k)) # 안전 범위
    
    # 2. 타겟 가격 계산
    target_price = curr['Open'] + (curr['Range'] * k)
    current_price = curr['Close']
    day_high = curr['High'] # 당일 고가 (실시간 갱신됨)

    # 변경: 5일 최고가 불러오기
    recent_high = curr['High5'] if 'High5' in curr else curr['High']
    
    # 3. 매수 조건 확인
    is_bull_market = current_price > curr['SMA20']
    volume_condition = curr['Volume'] > prev['Volume'] * 0.8
    is_breakout = current_price > target_price

    # (1) 고점 대비 하락폭 체크
    # 목표가를 뚫고 한참 올라갔다가($110), 다시 내려오는 중($102)이라면 사지 마라!
    # "현재가가 당일 고점의 98.1% 수준은 유지해야 한다" (1.9% 이상 밀리면 탈락)
    threshold_ratio = 0.98
    is_near_high = current_price >= (day_high * threshold_ratio)
    
    # (2) 꼬리 위험 감지
    # 고점이 목표가보다 훨씬 높았는데(이미 시세 줌), 지금 가격이 내려왔다면 위험
    is_falling_knife = (day_high > target_price * 1.02) and (current_price < day_high * 0.98)
    
    # -----------------------------------------------------------
    # 🟢 [매수 신호]
    # -----------------------------------------------------------
    if current_price > target_price and is_bull_market and volume_condition:

        # 🚨 필터링: 이미 고점 찍고 내려오는 놈이면 패스
        if not is_near_high:
            pct_drop = ((day_high - current_price) / day_high) * 100
            return 'none', f"고점대비하락(-{pct_drop:.1f}%)", 0
        if is_falling_knife:
             return 'none', "하락반전_감지", 0

        return 'buy', f"스마트_돌파(k={k:.2f}, Vol_OK+고점유지)", 0

    # -----------------------------------------------------------
    # 🔴 [매도 신호] (백테스트 최적화 적용)
    # -----------------------------------------------------------
    
    # 1. RSI 과열 익절 (기준 85로 상향 -> 더 비쌀 때 팜)
    current_rsi = curr['RSI'] if 'RSI' in curr and not pd.isna(curr['RSI']) else 50

    #if current_rsi > 85:
    #    return 'sell', f"RSI초과열({current_rsi:.0f})_익절", 0

    # 2. ✅ [사용자 요청] 조건부 트레일링 스탑 (어깨에서 팔기)
    # 조건: "RSI가 80 이상으로 뜨거운데" + "고점 대비 5% 꺾였다" -> 익절
    if current_rsi >= 80:
        if current_price < (recent_high * 0.95):
            return 'sell', f"5일고점대비(-5%)반납_익절(RSI {current_rsi:.0f})", 0
    # 2. 일반 상태일 때 (RSI 80 미만) 
    else: 
        if current_price < (recent_high * 0.90): # 10% 하락 시 매도
             return 'sell', f"추세훼손(-10%)_손절", 0
    
    # 3. 20일선 이탈 (Buffer 1% 적용 -> 휩소 방어)
    sma20_buffer = curr['SMA20'] * 0.99
    if current_price < sma20_buffer:
        return 'sell', "추세이탈(SMA20)_매도", 0
        
    return 'none', '', 0

# ✅ 1. 신규 전략 추가 (PRO 버전)
def strat_smart_momentum_pro(curr, prev, setting):
    """
    [전략] 스마트 모멘텀 PRO (5단계 레벨 + 가변형 트레일링 스탑)
    """
    # 레벨 파싱 (기본값 Lv 2)
    level = setting.get('level', 2)
    
    # [티어별 스탯 설정]
    if level == 5: # 🐲 드래곤 (3배 ETF)
        gap_trigger = 0.01; k_discount = 5.0; vol_ratio = 0.3
        drop_base = 0.90; drop_tight = 0.95; rsi_hot = 90
    elif level == 4: # 🥷 어쌔신 (급등주)
        gap_trigger = 0.02; k_discount = 3.0; vol_ratio = 0.5
        drop_base = 0.93; drop_tight = 0.96; rsi_hot = 85
    elif level == 3: # 🏹 헌터 (성장주)
        gap_trigger = 0.02; k_discount = 2.0; vol_ratio = 0.6
        drop_base = 0.94; drop_tight = 0.97; rsi_hot = 80
    elif level == 1: # 🛡️ 탱커 (안전형)
        gap_trigger = 0.05; k_discount = 1.0; vol_ratio = 1.0
        drop_base = 0.97; drop_tight = 0.985; rsi_hot = 75
    else: # ⚔️ 전사 (표준)
        gap_trigger = 0.03; k_discount = 1.5; vol_ratio = 0.8
        drop_base = 0.95; drop_tight = 0.97; rsi_hot = 80
    
    # 🔴 [매도] 가변형 트레일링 스탑
    current_price = curr['Close']
    # High5가 있으면 쓰고, 없으면 당일 High 사용
    h5 = curr.get('High5', 0)
    today_high = curr['High']
    recent_high = max(h5, today_high)
    
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

    # 🛡️ [방어 1] 갭하락 출발 금지
    gap_start = (curr['Open'] - prev['Close']) / prev['Close']
    if gap_start < -0.02:
        if level < 5: return 'none', f"갭하락({gap_start*100:.1f}%)_Pass", 0
        elif gap_start < -0.04: return 'none', f"폭락출발({gap_start*100:.1f}%)_Pass", 0
        
    # 🛡️ [방어 2] 20일선 우하향 금지
    sma20_slope = curr['SMA20'] - prev['SMA20']
    if sma20_slope < 0 and level < 4:
        return 'none', "20일선_우하향_Pass", 0


    # 🟢 [매수] 
    k = curr.get('NoiseMA20', 0.5)
    if pd.isna(k): k = 0.5
    
    # 갭상승 K 할인
    if gap_start >= gap_trigger:
        k = max(0.3, k - (gap_start * k_discount))
    k = max(0.3, min(0.7, k))

    target_price = curr['Open'] + (prev['Range'] * k)
    
    is_bull = current_price > curr['SMA20']
    is_breakout = current_price > target_price
    is_vol_ok = curr['Volume'] > prev['Volume'] * vol_ratio
    
    # 🛡️ [NEW] 추격 매수 제한 (Target Price + 3% 이상이면 포기)
    # 목표가가 100불인데 현재 104불이면 -> "너무 올랐다, 보내주자"
    limit_cap = target_price * 1.03 
    is_not_too_high = current_price <= limit_cap

    # 조건에 is_not_too_high 추가
    if is_breakout and is_bull and is_vol_ok:
        if is_not_too_high:
            return 'buy', f"PRO_돌파(Lv.{level}, k={k:.2f})", 0
        else:
            # 돌파는 했지만 너무 비싸서 패스하는 경우
            return 'none', f"돌파했으나_과열(Target초과)_Pass", 0

    return 'none', '', 0

def get_signal(strategy_name, curr, prev, setting):
    """
    [Dispatcher] 전략 이름에 따라 알맞은 함수 호출
    :return: (Signal, Reason, Qty) -> Qty는 Trader 클래스에서 자금사정에 맞춰 계산하므로 여기선 0 리턴
    """
    # 1. 변동성 돌파 (기본)
    if strategy_name == "VOLATILITY_BREAKOUT":
        return strat_volatility_breakout(curr, prev, setting)
    
    # 2. 스마트 모멘텀 
    if strategy_name == "SMART_MOMENTUM":
        return strat_smart_momentum(curr, prev, setting)
    
    # 3. MACD + RSI + SMA60 (대형주)
    if strategy_name == "MACD_RSI_OPTIMIZED":
        return strat_macd_rsi_optimized(curr, prev, setting)
    
    # [NEW] 신규 전략 연결
    if strategy_name == "SMART_PRO":
        return strat_smart_momentum_pro(curr, prev, setting)
    
    # 기본: MACD + RSI
    return strat_macd_rsi(curr, prev, setting)