import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.main_controller import MainController

if __name__ == "__main__":
    
    # 2. 컨트롤러 실행
    controller = MainController()
    controller.run()