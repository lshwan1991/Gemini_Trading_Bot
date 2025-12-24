import pandas as pd

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
    - 백테스트 검증 완료: 연수익 약 16% / MDD -21%
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
    
    # 3. 매수 조건 확인
    is_bull_market = current_price > curr['SMA20']
    volume_condition = curr['Volume'] > prev['Volume'] * 0.8
    
    # -----------------------------------------------------------
    # 🟢 [매수 신호]
    # -----------------------------------------------------------
    if current_price > target_price and is_bull_market and volume_condition:
        return 'buy', f"스마트_돌파(k={k:.2f},Vol_OK)", 0

    # -----------------------------------------------------------
    # 🔴 [매도 신호] (백테스트 최적화 적용)
    # -----------------------------------------------------------
    
    # 1. RSI 과열 익절 (기준 85로 상향 -> 더 비쌀 때 팜)
    # (RSI 데이터가 없을 경우 안전하게 50으로 처리)
    current_rsi = curr['RSI'] if 'RSI' in curr and not pd.isna(curr['RSI']) else 50
    if current_rsi > 85:
        return 'sell', f"RSI초과열({current_rsi:.0f})_익절", 0

    # 2. [삭제됨] SMA5 트레일링 스톱 
    # (너무 일찍 팔아서 수익을 못 먹는 문제 해결 -> 삭제)

    # 3. 20일선 이탈 (Buffer 1% 적용 -> 휩소 방어)
    sma20_buffer = curr['SMA20'] * 0.99
    if current_price < sma20_buffer:
        return 'sell', "추세이탈(SMA20)_매도", 0
        
    return 'none', '', 0

def get_signal(strategy_name, curr, prev, setting):
    """
    [Dispatcher] 전략 이름에 따라 알맞은 함수 호출
    :return: (Signal, Reason, Qty) -> Qty는 Trader 클래스에서 자금사정에 맞춰 계산하므로 여기선 0 리턴
    """
    if strategy_name == "VOLATILITY_BREAKOUT":
        return strat_volatility_breakout(curr, prev, setting)
    
    # 👇 새로 추가된 전략 연결
    if strategy_name == "SMART_MOMENTUM":
        return strat_smart_momentum(curr, prev, setting)
    
    # 👇 [추가] 대형주 전용 전략 연결
    if strategy_name == "MACD_RSI_OPTIMIZED":
        return strat_macd_rsi_optimized(curr, prev, setting)
    
    return strat_macd_rsi(curr, prev, setting)