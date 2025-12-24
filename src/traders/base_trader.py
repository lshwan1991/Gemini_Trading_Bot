import pandas as pd
import time
from abc import ABC, abstractmethod

class BaseTrader(ABC):
    def __init__(self, auth_manager):
        self.auth_manager = auth_manager
        self.token = None
    
    def refresh_token(self):
        self.token = self.auth_manager.get_token()

    @abstractmethod
    def get_balance(self):
        pass

    @abstractmethod
    def get_daily_data(self, code):
        pass

    @abstractmethod
    def send_order(self, code, side, price, qty):
        pass

    def calculate_indicators(self, data_list):
        """지표 계산 (MACD, RSI, 변동성, +이동평균선)"""
        # 데이터가 너무 적으면(20일 미만) 이평선 계산 불가하므로 빈 DF 리턴
        if not data_list or len(data_list) < 20: 
            return pd.DataFrame()
        
        df = pd.DataFrame(data_list)
        
        # 날짜 오름차순 정렬 (과거 -> 오늘)
        if df.iloc[0]['Date'] > df.iloc[-1]['Date']:
            df = df.iloc[::-1].reset_index(drop=True)
        else:
            df = df.sort_values(by="Date").reset_index(drop=True)
            
        # 1. 이동평균선 (SMA)
        df['SMA5'] = df['Close'].rolling(window=5).mean()
        df['SMA20'] = df['Close'].rolling(window=20).mean()
        df['SMA60'] = df['Close'].rolling(window=60).mean()
        
        # ---------------------------------------------------------
        # 🆕 [NEW] 노이즈 비율 계산 (동적 K 만들기)
        # ---------------------------------------------------------
        # 공식: 1 - (|시가-종가| / (고가-저가))
        # (고가-저가)가 0인 경우(거래정지 등) 0으로 처리하여 에러 방지
        range_size = df['High'] - df['Low']
        body_size = (df['Open'] - df['Close']).abs()
        
        # 노이즈 = 1 - (몸통 / 전체길이)
        # 꼬리가 길수록 1에 가깝고, 몸통이 꽉 찰수록 0에 가깝음
        df['Noise'] = 1 - (body_size / range_size.replace(0, 1)) 
        
        # 최근 20일 평균 노이즈를 'k' 값으로 사용
        df['NoiseMA20'] = df['Noise'].rolling(window=20).mean()
        # ---------------------------------------------------------


        # 2. MACD
        df['EMA12'] = df['Close'].ewm(span=12).mean()
        df['EMA26'] = df['Close'].ewm(span=26).mean()
        df['MACD'] = df['EMA12'] - df['EMA26']
        df['Signal'] = df['MACD'].ewm(span=9).mean()
        
        # 3. RSI
        delta = df['Close'].diff(1)
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        rs = gain.rolling(14).mean() / loss.rolling(14).mean()
        df['RSI'] = 100 - (100 / (1 + rs))
        
        # 4. 변동성 (Range)
        df['Range'] = df['High'].shift(1) - df['Low'].shift(1)
        
        return df