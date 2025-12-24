import requests
import json
import time
import os
from config import Config

class AuthManager:
    def __init__(self):
        self.access_token = None
        self.token_path = "data/token_save.json"

    def get_token(self):
        # 1. 캐시 확인
        if os.path.exists(self.token_path):
            try:
                with open(self.token_path, 'r') as f:
                    data = json.load(f)
                if time.time() - data['timestamp'] < 21600: # 6시간
                    return data['access_token']
            except: pass

        # 2. 재발급
        return self._issue_new_token()

    def _issue_new_token(self):
        url = f"{Config.URL_BASE}/oauth2/tokenP"
        body = {
            "grant_type": "client_credentials",
            "appkey": Config.APP_KEY,
            "appsecret": Config.APP_SECRET
        }
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

    def get_hashkey(self, datas):
        url = f"{Config.URL_BASE}/uapi/hashkey"
        headers = {
            "content-type": "application/json",
            "appkey": Config.APP_KEY,
            "appsecret": Config.APP_SECRET
        }
        res = requests.post(url, headers=headers, data=json.dumps(datas))
        return res.json()["HASH"] if res.status_code == 200 else ""