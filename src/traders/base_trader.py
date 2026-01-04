import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
import time
from abc import ABC, abstractmethod
import numpy as np

class BaseTrader(ABC):
    def __init__(self, auth_manager):
        self.auth_manager = auth_manager
        # 자식 클래스(KoreaTrader, USTrader)가 이 변수들을 사용합니다.
        self.app_key = auth_manager.app_key
        self.app_secret = auth_manager.app_secret
        self.url_base = auth_manager.url_base
        self.account_no = auth_manager.account_no
        self.mode = auth_manager.mode

        # 토큰 초기화
        self.token = self.auth_manager.get_token()

        # ✅ [핵심] 차트 데이터 캐싱 및 타이머 추가
        self.market_data_cache = {}  # { 'CODE': DataFrame }
        self.last_chart_update_time = 0 # 마지막으로 일봉을 갱신한 시간
        self.CHART_REFRESH_INTERVAL = 600 # 10분 (600초)

        # ✅ [네트워크] 강력한 재시도 세션 생성
        self.session = self._create_retry_session()
    
    def refresh_token(self):
        self.token = self.auth_manager.get_token()

    @abstractmethod
    def get_balance(self):
        pass

    @abstractmethod
    def get_daily_data(self, code):
        pass

    @abstractmethod
    def get_current_price(self, code):
        """[NEW] 현재가 조회 (가벼운 API)"""
        pass

    @abstractmethod
    def send_order(self, code, side, price, qty):
        pass

    @abstractmethod
    def run(self):
        pass

    def _create_retry_session(self, retries=1, backoff_factor=0.1):
        """
        네트워크 불안정 시 지수 백오프(Exponential Backoff)로 재시도하는 세션 생성
        - retries: 최대 재시도 횟수
        - backoff_factor: 재시도 간격 (0.3초, 0.6초, 1.2초... 늘어남)
        """
        session = requests.Session()
        retry = Retry(
            total=retries,
            read=retries,
            connect=retries,
            backoff_factor=backoff_factor,
            status_forcelist=[500, 502, 503, 504], # 서버 에러 시 재시도
            allowed_methods=["GET", "POST"] # 모든 요청에 적용
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def calculate_indicators(self, data):
        """지표 계산 (MACD, RSI, 변동성, +이동평균선)"""
        # 데이터가 너무 적으면(20일 미만) 이평선 계산 불가하므로 빈 DF 리턴
        if not data: return pd.DataFrame()
        
        df = pd.DataFrame(data)
        
        # 날짜 오름차순 정렬 (과거 -> 오늘)
        if df.iloc[0]['Date'] > df.iloc[-1]['Date']:
            df = df.iloc[::-1].reset_index(drop=True)
        else:
            df = df.sort_values(by="Date").reset_index(drop=True)
            
        # 1. 이동평균선 (SMA)
        df['SMA5'] = df['Close'].rolling(window=5).mean()
        df['SMA20'] = df['Close'].rolling(window=20).mean()
        df['SMA60'] = df['Close'].rolling(window=60).mean()
        
        # 2. 노이즈 비율 계산 (동적 K)
        range_size = df['High'] - df['Low']
        body_size = (df['Open'] - df['Close']).abs()
        safe_range = range_size.replace(0, 1)
        df['Noise'] = 1 - (body_size / range_size.replace(0, 1)) 
        df['NoiseMA20'] = df['Noise'].rolling(window=20).mean()

        # 3. MACD
        df['EMA12'] = df['Close'].ewm(span=12).mean()
        df['EMA26'] = df['Close'].ewm(span=26).mean()
        df['MACD'] = df['EMA12'] - df['EMA26']
        df['Signal'] = df['MACD'].ewm(span=9).mean()
        
        # 4. RSI
        delta = df['Close'].diff(1)
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        rs = gain.rolling(14).mean() / loss.rolling(14).mean().replace(0, 1) # div 0 방지
        df['RSI'] = 100 - (100 / (1 + rs))
        
        # 5. 변동성 (Range)
        df['Range'] = df['High'].shift(1) - df['Low'].shift(1)

        # ✅ [수정] A/D Line 직접 계산
        # 고가-저가가 0인 경우(변동 없음) 1로 대체하여 에러 방지
        hl_range = df['High'] - df['Low']
        hl_range = hl_range.replace(0, 1) 
        
        mfm = ((df['Close'] - df['Low']) - (df['High'] - df['Close'])) / hl_range
        mfv = mfm * df['Volume']
        
        # A/D Line = MFV의 누적 합계
        df['AD'] = mfv.cumsum()
        
        # A/D Line의 20일 이동평균 (추세 판단용)
        df['AD_MA20'] = df['AD'].rolling(window=20).mean()
        
        # NaN 값 처리 (앞쪽 데이터 채우기 + 0 처리)
        df.bfill(inplace=True)
        df.fillna(0, inplace=True)

        
        return df