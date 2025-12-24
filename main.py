import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.auth import AuthManager
from src.main_controller import MainController

if __name__ == "__main__":
    # 1. 인증 관리자 초기화
    auth_manager = AuthManager()
    
    # 2. 컨트롤러 실행
    controller = MainController(auth_manager)
    controller.run()