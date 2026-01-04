# test_connection.py
import requests
import json

# ==========================================
# 👇 여기에 실전용 정보를 직접 적어서 테스트하세요
# ==========================================
APP_KEY = "PSmcpKwCNnjgVyTXGdurcob1MQEBzD8F0SQg"
APP_SECRET = "PyJWTux+6KXR339HEl8wR9HbKmW5+uUoIVyDymnUJ6qCEIpzxz+T4BcYS5KzryAQ2qyYWZk5b9b5WwIiCpgav9nWwvqibm2/zlt2k0VKMTn1Y5GE//YmBZLbNcgFfHjnw/hjoyygmL77k7f7O9npf8MGAwvZpMqcETznYWS7vDu4mwNILL8="
CANO = "64701311" # 계좌번호 앞 8자리 (스크린샷 기준)
ACNT_PRDT_CD = "01" # 뒷자리

# ✅ 실전투자 URL (정확히 이 주소여야 합니다)
URL_BASE = "https://openapi.koreainvestment.com:9443"

def test_connection():
    print(f"🚀 [진단 시작] 실전 서버({URL_BASE}) 접속 테스트...")

    # 1. 접근 토큰(Token) 발급 시도
    headers = {"content-type": "application/json"}
    body = {
        "grant_type": "client_credentials",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET
    }
    
    try:
        res = requests.post(f"{URL_BASE}/oauth2/tokenP", headers=headers, data=json.dumps(body))
        
        if res.status_code == 200:
            print("✅ [1단계 성공] 실전 서버 인증(Token) 완료!")
            access_token = res.json()['access_token']
        else:
            print(f"❌ [1단계 실패] 토큰 발급 실패. (응답코드: {res.status_code})")
            print(f"   👉 원인: {res.text}")
            return
            
    except Exception as e:
        print(f"❌ [치명적 오류] 서버 주소가 틀렸거나 인터넷 문제: {e}")
        return

    # 2. 아주 간단한 잔고 조회 (국내주식 잔고 API로 찔러보기)
    # (01 계좌는 국내 계좌 기반이므로 이 API가 더 응답을 잘 줄 수 있음)
    print("\n🔍 [2단계] 계좌 연결 테스트 (국내주식 잔고 조회 API)...")
    
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {access_token}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": "TTTC8434R" # 실전용 (체결기준 주식잔고 조회)
    }
    
    params = {
        "CANO": CANO,
        "ACNT_PRDT_CD": ACNT_PRDT_CD,
        "AFHR_FLPR_YN": "N",
        "OFL_YN": "N",
        "INQR_DVSN": "02",
        "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N",
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "00",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": ""
    }
    
    res = requests.get(f"{URL_BASE}/uapi/domestic-stock/v1/trading/inquire-balance", headers=headers, params=params)
    
    if res.status_code == 200:
        data = res.json()
        if data['rt_cd'] == '0':
            print("✅ [2단계 성공] 계좌 조회 성공!")
            print(f"   👉 메시지: {data['msg1']}")
            print("   🎉 결론: API 키와 서버 주소는 정상입니다. 이제 코드를 수정하면 됩니다.")
        else:
            print(f"❌ [2단계 실패] 조회는 됐지만 에러 반환: {data['msg1']}")
    else:
        print(f"❌ [2단계 실패] 서버 응답 에러: {res.text}")

if __name__ == "__main__":
    test_connection()