import requests
import time
import threading
import queue
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from config import Config

# =========================================================
# ⚙️ [설정] 네트워크 세션 및 큐 초기화
# =========================================================

# 1. 세션 설정 (속도 향상)
session = requests.Session()
retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
session.mount('https://', HTTPAdapter(max_retries=retries))

# 2. 메시지 대기열 (Queue) 생성
# 메인 봇이 여기다 메시지를 던져넣고 바로 할 일을 하러 갑니다.
msg_queue = queue.Queue()

# =========================================================
# 👷 [일꾼] 백그라운드 전송 담당자
# =========================================================
def _telegram_worker():
    """
    큐에 쌓인 메시지를 하나씩 꺼내서 실제로 전송하는 함수
    (이 함수는 별도의 쓰레드에서 영원히 돌아갑니다)
    """
    while True:
        try:
            # 큐에서 메시지 꺼내기 (없으면 대기)
            message = msg_queue.get()
            
            if message is None: # 종료 신호
                break

            # --- 실제 전송 로직 시작 ---
            token = Config.TELEGRAM_TOKEN
            chat_id = Config.TELEGRAM_ID
            
            if token and chat_id:
                # 4096자 분할 처리
                msgs_to_send = []
                if len(message) > 4000:
                    msgs_to_send.append(message[:4000])
                    msgs_to_send.append(message[4000:])
                else:
                    msgs_to_send.append(message)

                url = f"https://api.telegram.org/bot{token}/sendMessage"

                for sub_msg in msgs_to_send:
                    data = {"chat_id": chat_id, "text": sub_msg}
                    
                    # 재시도 로직
                    for attempt in range(3):
                        try:
                            resp = session.post(url, data=data, timeout=10)
                            if resp.status_code == 200:
                                break
                            elif resp.status_code == 429: # 도배 방지
                                time.sleep(5)
                        except Exception as e:
                            print(f"⚠️ [Telegram Worker] 전송 에러: {e}")
                            time.sleep(1)
            # --- 실제 전송 로직 끝 ---
            
            # 작업 완료 표시
            msg_queue.task_done()
            
            # 메시지 간 너무 빠르면 텔레그램이 차단하므로 0.05초 휴식
            time.sleep(0.05) 

        except Exception as e:
            print(f"🚨 [Telegram Worker] 치명적 오류: {e}")

# 3. 봇 시작 시 일꾼(쓰레드) 채용 및 가동
# daemon=True로 설정하면 메인 프로그램 종료 시 같이 사라짐
worker_thread = threading.Thread(target=_telegram_worker, daemon=True)
worker_thread.start()



def send_telegram_msg(message):
    """
    메시지를 큐에 넣기만 하고 즉시 리턴함 (Non-blocking)
    매매 로직에 전혀 영향을 주지 않음 (소요시간 0.00001초)
    """
    msg_queue.put(message)