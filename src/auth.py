import requests
import json
import time
import os
from config import Config

class AuthManager:
    def __init__(self,app_key, app_secret, url_base, account_no, mode):
        self.app_key = app_key
        self.app_secret = app_secret
        self.url_base = url_base
        self.account_no = account_no
        self.mode = mode
        self.token_path = f"data/token_{self.mode.lower()}.json"
        self.access_token = None

    def get_token(self):
        # 1. 캐시 확인
        if os.path.exists(self.token_path):
            try:
                with open(self.token_path, 'r') as f:
                    data = json.load(f)
                # 유효기간 체크 (6시간 = 21600초)
                if time.time() - data['timestamp'] < 21600: 
                    self.access_token = data['access_token']
                    return self.access_token
            except: pass

        # 2. 만료되었거나 없으면 재발급
        return self._issue_new_token()      

    def _issue_new_token(self):
        url = f"{self.url_base}/oauth2/tokenP"
        body = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,       # ✅ Config 대신 self.app_key 사용
            "appsecret": self.app_secret  # ✅ Config 대신 self.app_secret 사용
        }
        try:
            res = requests.post(url, headers={"content-type": "application/json"}, data=json.dumps(body))
            
            if res.status_code == 200:
                token = res.json()['access_token']
                if not os.path.exists('data'): os.makedirs('data')
                with open(self.token_path, 'w') as f:
                    json.dump({"access_token": token, "timestamp": time.time()}, f)
                    
                print("✅ [Auth] 토큰 갱신 완료")
                return token
            else:
                raise Exception(f"토큰 발급 실패: {res.text}")
            
        except Exception as e:
            print(f"❌ [{self.mode}] 통신 에러: {e}")
            raise

    def get_hashkey(self, datas):
        url = f"{self.url_base}/uapi/hashkey"
        headers = {
            "content-type": "application/json",
            "appkey": self.app_key,       # ✅ self 변수 사용
            "appsecret": self.app_secret  # ✅ self 변수 사용
        }
        try:
            res = requests.post(url, headers=headers, data=json.dumps(datas))
            return res.json()["HASH"] if res.status_code == 200 else ""
        except:
            return ""