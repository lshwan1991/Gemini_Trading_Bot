import requests
import os
from config import Config

def send_telegram_msg(message):
    try:
        token = Config.TELEGRAM_TOKEN
        chat_id = Config.TELEGRAM_ID
        if token and chat_id:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            requests.get(url, params={"chat_id": chat_id, "text": message}, timeout=5)
    except Exception as e:
        print(f"⚠️ 텔레그램 에러: {e}")
