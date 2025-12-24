import json
import os

def load_target_stocks(market_type="KR"):
    """
    [기능] 타겟 종목 리스트 로드
    :param market_type: "KR" (한국) or "US" (미국)
    :return: 타겟 리스트 (List[Dict])
    """
    targets = []
    
    # 1. 파일 경로 설정
    if market_type == "KR":
        file_path = "data/targets_kr.json"
    else:
        file_path = "data/targets_us.json"

    # 2. 파일 읽기
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                targets = json.load(f)
                
                # 미국 종목의 경우 market 태그 강제 주입
                if market_type == "US":
                    for item in targets:
                        item['market'] = 'US'
                        
                print(f"📂 [{market_type}] 타겟 {len(targets)}개 로드 완료")
        except Exception as e:
            print(f"⚠️ {market_type} 타겟 파일 로드 실패: {e}")
    else:
        print(f"⚠️ {file_path} 파일이 없습니다.")

    return targets