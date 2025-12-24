import requests
import json
import time
from src.config import Config

class USTrader:
    def __init__(self, token_manager):
        self.token_manager = token_manager
        
    def buy_stock(self, code, qty, price, exchange="NASD"):
        """
        [미국] 주식 지정가 매수
        :param code: 종목코드 (예: TSLA, AAPL)
        :param qty: 주문 수량
        :param price: 주문 가격 (달러, 소수점 2자리)
        :param exchange: 거래소 (NASD:나스닥, NYSE:뉴욕, AMEX:아멕스)
        """
        # 1. 토큰 확보
        token = self.token_manager.get_token()
        
        path = "/uapi/overseas-stock/v1/trading/order"
        url = f"{Config.URL_BASE}{path}"
        
        # 2. 거래 ID (TrID) 설정
        # 모의투자(PAPER) vs 실전투자(REAL) 코드가 다름!
        if Config.MODE == "PAPER":
            tr_id = "VTTT1002U" # [모의] 미국 매수
        else:
            tr_id = "JTTT1002U" # [실전] 미국 매수

        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": Config.APP_KEY,
            "appsecret": Config.APP_SECRET,
            "tr_id": tr_id,
        }
        
        # 3. 주문 파라미터 구성
        data = {
            "CANO": Config.ACCOUNT_NO,          # 계좌번호 앞 8자리
            "ACNT_PRDT_CD": "01",               # 계좌번호 뒤 2자리 (보통 01)
            "OVRS_EXCG_CD": exchange,           # 거래소 코드 (NASD, NYSE 등)
            "PDNO": code,                       # 종목코드 (티커)
            "ORD_QTY": str(int(qty)),           # 주문 수량
            "OVRS_ORD_UNPR": f"{price:.2f}",    # 주문 가격 (문자열, 소수점 2자리 필수)
            "ORD_SVR_DVSN_CD": "0",             # 주문서버구분 (0 고정)
            "ORD_DVSN": "00"                    # 주문구분 (00: 지정가)
        }
        
        print(f"🇺🇸 [매수 요청] {code} ({exchange}) | {qty}주 | ${price}")
        
        try:
            res = requests.post(url, headers=headers, data=json.dumps(data))
            res_data = res.json()
            
            if res_data['rt_cd'] == '0':
                print(f"✅ [매수 성공] 주문번호: {res_data['output']['ODNO']}")
                return True
            else:
                print(f"❌ [매수 실패] {res_data['msg1']} (Code: {res_data['msg_cd']})")
                return False
                
        except Exception as e:
            print(f"⚠️ [시스템 에러] {e}")
            return False