import pandas as pd
from datetime import datetime
import pytz

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

def strat_lw_ad_hybrid(curr, prev, setting):
    """
    🆕 [신규 전략] 래리 윌리엄스 변동성 돌파 + A/D Line 필터
    - 변동성 돌파 시그널이 나와도, 세력 매집(A/D 상승)이 없으면 무시함
    - 가짜 돌파(Fake Breakout)를 걸러내는 것이 목적
    """
    # 0. 데이터 검증 (A/D 계산값 존재 여부)
    if 'AD' not in curr or 'AD_MA20' not in curr:
        return 'none', 'AD_데이터_없음', 0
    if pd.isna(curr['AD']) or pd.isna(curr['AD_MA20']):
        return 'none', 'AD_계산불가', 0

    k = setting.get('k', 0.5)

    # ✅ [설정] 시장 구분 (기본값 KR)
    market_type = setting.get('market', 'KR')

    # 1. 현재 시간 확인 (한국 시간)
    now = datetime.now(pytz.timezone('Asia/Seoul'))
    hm = int(now.strftime("%H%M"))

    # 변수 초기화 (매도 시간, 진입 허용 시간)
    is_sell_time = False
    is_wait_time = False
    

    # -----------------------------------------------------------
    # 🇰🇷 [한국 시장] 시간표 (09:00 ~ 15:30)
    # -----------------------------------------------------------
    if market_type == 'KR':
        # 1. 시가 청산 (09:00 ~ 09:10)
        if 900 <= hm <= 910:
            is_sell_time = True
            
        # 2. 오전 관망 (09:11 ~ 12:30) - 휩소 방지
        elif hm < 1230:
            is_wait_time = True

    # -----------------------------------------------------------
    # 🇺🇸 [미국 시장] 시간표 (23:30 ~ 06:00)
    # -----------------------------------------------------------
    # 매도 시간을 넉넉하게 잡고, 진입 시간을 01:30(새벽) 이후로 설정
    else:
        # 1. 시가 청산 (22:30 ~ 23:50)
        # 장 시작하자마자 파는 구간 (썸머/윈터 모두 포함)
        if 2330 <= hm <= 2359: 
            is_sell_time = True
            
        # 2. 초반 관망 (00:00 ~ 01:30) - 미국장 초반 변동성 회피
        # 자정이 넘어가면 hm이 0부터 시작하므로 조건이 달라짐
        # (예: 22시, 23시 혹은 00시, 01시 30분 전이면 대기)
        elif (2200 <= hm < 2330) or (0 <= hm < 130): 
            is_wait_time = True

    # ===========================================================
    # 🚦 [판단] 로직 수행
    # ===========================================================
    
    # 1. [매도] 시가 청산 타임이면 무조건 매도
    if is_sell_time:
        return 'sell', f"시가청산({market_type}_Open)", 0

    # 2. [대기] 관망 타임이면 진입 금지
    if is_wait_time:
        return 'none', f"{market_type}_변동성_관망중", 0

    # 3. [진입] 진짜 추세 확인 후 진입
    # KR: 12:30 이후 / US: 01:30 이후
    target_price = curr['Open'] + (curr['Range'] * k)
    current_price = curr['Close']
    is_ad_bullish = curr['AD'] > curr['AD_MA20']

    # 🟢 [매수]
    if current_price >= target_price:
        if is_ad_bullish:
             return 'buy', f"추세확인_돌파(k={k})", 0
        else:
            # 돌파는 했으나 A/D가 꺾여있음 -> 매수 안 함
            return 'none', '', 0

    # 🔴 [손절] 방어 로직
    if current_price < curr['Open']:
        return 'sell', "시가이탈_손절", 0
    
    current_rsi = curr['RSI'] if 'RSI' in curr and not pd.isna(curr['RSI']) else 50
    if current_rsi > 85:
        return 'sell', f"RSI초과열({current_rsi:.0f})_익절", 0

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

    if current_rsi > 85:
        return 'sell', f"RSI초과열({current_rsi:.0f})_익절", 0
    
    # 2. ✅ [사용자 요청] 조건부 트레일링 스탑 (어깨에서 팔기)
    # 조건: "RSI가 80 이상으로 뜨거운데" + "고점 대비 5% 꺾였다" -> 익절
    if current_rsi >= 80:
        if current_price < (day_high * 0.95):
            return 'sell', f"고점(-5%)반납_익절(RSI {current_rsi:.0f})", 0
    
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
    # 1. 변동성 돌파 (기본)
    if strategy_name == "VOLATILITY_BREAKOUT":
        return strat_volatility_breakout(curr, prev, setting)
    
    # 2. 스마트 모멘텀 (노이즈 필터)
    if strategy_name == "SMART_MOMENTUM":
        return strat_smart_momentum(curr, prev, setting)
    
    # 3. MACD + RSI + SMA60 (대형주)
    if strategy_name == "MACD_RSI_OPTIMIZED":
        return strat_macd_rsi_optimized(curr, prev, setting)
    
    # 🆕 4. LW + AD Hybrid (신규 추가)
    if strategy_name == "LW_AD_HYBRID":
        return strat_lw_ad_hybrid(curr, prev, setting)
    
    # 기본: MACD + RSI
    return strat_macd_rsi(curr, prev, setting)