import requests
import json
import pandas as pd
import time
from datetime import datetime
from config import Config

# ==========================================
# 1. 전역 변수 (상태 관리용)
# ==========================================
IS_HOLDING = False # 현재 주식을 가지고 있나요? (True/False)

# ==========================================
# 2. API 통신 도구
# ==========================================
# 🔔 알림 봇 함수 (NEW!)
# ==========================================
def send_telegram_msg(message):
    """
    텔레그램으로 메시지를 발송하는 함수
    """
    token = Config.TELEGRAM_TOKEN
    chat_id = Config.TELEGRAM_ID
    
    if not token or not chat_id:
        return # 설정 안되어 있으면 무시

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    params = {
        "chat_id": chat_id,
        "text": message
    }
    
    try:
        # 전송 시도
        requests.get(url, params=params)
    except Exception as e:
        print(f"❌ 텔레그램 전송 실패: {e}")

def get_access_token():
    """
    토큰 발급 (에러 디버깅 기능 강화)
    """
    url = f"{Config.BASE_URL}/oauth2/tokenP"
    
    # 1. 현재 설정된 키 확인 (로그 출력)
    print("=" * 40)
    print(f"🔑 [{Config.MODE}] 토큰 발급을 시도합니다.")
    print(f"   👉 접속 주소: {Config.BASE_URL}")
    
    # 키가 비어있는지 확인
    if not Config.APP_KEY or not Config.APP_SECRET:
        raise Exception(f"❌ {Config.MODE} 모드의 APP_KEY 또는 SECRET이 설정되지 않았습니다! .env 파일을 확인하세요.")

    print(f"   👉 앱키(앞5자리): {Config.APP_KEY[:5]}***")
    print("=" * 40)

    headers = {"content-type": "application/json"}
    body = {
        "grant_type": "client_credentials",
        "appkey": Config.APP_KEY,
        "appsecret": Config.APP_SECRET
    }
    
    # 2. 요청 전송
    response = requests.post(url, headers=headers, data=json.dumps(body))
    res_data = response.json()
    
    # 3. 성공/실패 여부 확실하게 체크
    if response.status_code == 200 and 'access_token' in res_data:
        print("✅ 토큰 발급 성공!")
        return res_data['access_token']
    else:
        # 실패 시, 서버가 알려준 에러 메시지를 그대로 출력
        print("\n❌ 토큰 발급 실패! (로그인 거절)")
        print(f"응답 코드: {response.status_code}")
        print(f"🚨 에러 메시지: {res_data}") 
        print("="*40)
        raise Exception("API 인증 실패: 위 에러 메시지를 확인해서 키 값을 수정하세요.")

def get_1min_chart(token, symbol_code):
    """
    ⚡ [테스트용] 1분봉 데이터 조회 (당일)
    가장 빠르게 변하는 데이터를 가져옵니다.
    """
    path = "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
    url = f"{Config.BASE_URL}/{path}"

    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": Config.APP_KEY,
        "appsecret": Config.APP_SECRET,
        "tr_id": "FHKST01010450", # 1분봉 조회 ID
        "custtype": "P",
    }
    params = {
        "fid_etc_cls_code": "",
        "fid_cond_mrkt_div_code": "J",
        "fid_input_iscd": symbol_code,
        "fid_input_hour_1": "", 
        "fid_pw_data_incu_yn": "Y"
    }
    res = requests.get(url, headers=headers, params=params)
    
    minute_data = []
    if res.status_code == 200 and 'output2' in res.json():
        for row in res.json()['output2']:
            minute_data.append({
                "Time": row['stck_cntg_hour'],
                "Close": int(row['stck_prpr'])
            })
    
    df = pd.DataFrame(minute_data)
    # 최신 데이터가 위로 오기 때문에 뒤집어서 (과거->현재) 순서로 만듦
    df = df.iloc[::-1].reset_index(drop=True)
    return df

def send_order(token, symbol_code, side):
    """
    주문 전송 함수 (매수/매도 통합)
    side: 'BUY' 또는 'SELL'
    """
    path = "/uapi/domestic-stock/v1/trading/order-cash"
    url = f"{Config.BASE_URL}/{path}"
    
    # 모드에 따른 TR_ID 설정
    if Config.MODE == 'PAPER':
        # 모의투자: 매수(VTTC0012U) / 매도(VTTC0011U)
        tr_id = "VTTC0012U" if side == 'BUY' else "VTTC0011U"
    else:
        # 실전투자: 매수(TTTC0012U) / 매도(TTTC0011U)
        tr_id = "TTTC0012U" if side == 'BUY' else "TTTC0011U"

    data = {
        "CANO": Config.ACCOUNT_NO,
        "ACNT_PRDT_CD": "01",
        "PDNO": symbol_code,
        "ORD_DVSN": "01", # 시장가 (무조건 체결)
        "ORD_QTY": "1",   # 테스트니까 1주씩만
        "ORD_UNPR": "0",
    }
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": Config.APP_KEY,
        "appsecret": Config.APP_SECRET,
        "tr_id": tr_id,
        "custtype": "P",
    }
    
    action_name = "매수" if side == 'BUY' else "매도"
    print(f"⚡ [{Config.MODE}] {symbol_code} {action_name} 주문 전송!")
    
    # [수정] 주문 전송 성공 부분
    res = requests.post(url, headers=headers, data=json.dumps(data))
    if res.status_code == 200 and res.json()['rt_cd'] == '0':
        odno = res.json()['output']['ODNO']
        msg = f"✅ [{side}] 체결 성공!\n종목: {symbol_code}\n주문번호: {odno}"
        
        print(msg)            # 1. 컴퓨터 화면에 출력
        send_telegram_msg(msg) # 2. 📱 핸드폰으로 전송!
        return True
    else:
        # 실패시에도 알림 받고 싶으면 여기에 추가
        err_msg = f"❌ [{side}] 주문 실패\n사유: {res.json().get('msg1', '알수없음')}"
        print(err_msg)
        send_telegram_msg(err_msg)
        return False

# ==========================================
# 3. 🧠 초단타 전략 (Brain)
# ==========================================
def scalping_strategy(token, symbol):
    global IS_HOLDING # 전역 변수 사용
    
    # 1. 1분봉 데이터 가져오기
    df = get_1min_chart(token, symbol)
    if df.empty:
        return

    # 2. 아주 민감한 이평선 계산 (3분 vs 10분)
    df['MA3'] = df['Close'].rolling(window=3).mean()
    df['MA10'] = df['Close'].rolling(window=10).mean()
    
    curr = df.iloc[-1] # 현재 봉
    prev = df.iloc[-2] # 직전 봉 (1분 전)
    
    print(f"\n📊 [1분봉] 현재가: {curr['Close']} | MA3: {curr['MA3']:.0f} | MA10: {curr['MA10']:.0f}")

    # 3. 매매 로직
    # (1) 매수 조건: 3분선이 10분선을 뚫고 올라감 (골든크로스) + 내가 주식이 없음
    if not IS_HOLDING:
        if prev['MA3'] < prev['MA10'] and curr['MA3'] > curr['MA10']:
            print("🚀 [단타 신호] 골든크로스! 매수합니다.")
            if send_order(token, symbol, 'BUY'):
                IS_HOLDING = True # 상태 변경: 이제 주식 있음
        else:
            print("💤 매수 기회 노려보는 중... (주식 없음)")
            
    # (2) 매도 조건: 3분선이 10분선 아래로 떨어짐 (데드크로스) + 내가 주식이 있음
    elif IS_HOLDING:
        if prev['MA3'] > prev['MA10'] and curr['MA3'] < curr['MA10']:
            print("💧 [단타 신호] 데드크로스! 이익 실현(또는 손절)합니다.")
            if send_order(token, symbol, 'SELL'):
                IS_HOLDING = False # 상태 변경: 이제 주식 없음
        else:
            print("💰 익절/손절 타이밍 재는 중... (보유 중)")

# ==========================================
# 4. 실행 (장시간 돌리기)
# ==========================================
def is_market_open():
    now = int(datetime.now().strftime("%H%M"))
    return 900 <= now <= 1530

if __name__ == "__main__":
    print("🏎️ [TEST MODE] 초단타 트레이딩 봇 시작!")
    token = get_access_token()
    symbol = "005930" # 삼성전자
    
    send_telegram_msg(f"🤖 [{Config.MODE}] 트레이딩 봇이 시작되었습니다!")

    # 상태 초기화 (봇 켤 때 주식이 없다고 가정)
    IS_HOLDING = False 
    
    while True:
        if is_market_open():
            try:
                scalping_strategy(token, symbol)
            except Exception as e:
                print(f"에러 발생: {e}")
        else:
            print(f"장 마감 (현재시간: {datetime.now().strftime('%H:%M')})")
        
        # 테스트니까 1분도 길다. 30초마다 체크!
        time.sleep(30)