import FinanceDataReader as fdr
import pandas as pd
import os
from datetime import datetime, timedelta

# ==========================================
# 🛠️ 설정: 백테스트할 종목들
# ==========================================
targets = [
    {"code": "005930", "name": "삼성전자", "type": "STOCK"},
    {"code": "000660", "name": "SK하이닉스", "type": "STOCK"},
    {"code": "122630", "name": "KODEX레버리지2배", "type": "ETF"},
    {"code": "252670", "name": "KODEX_200선물인버스2X", "type": "ETF"},
    {"code": "107640", "name": "한중엔시에스", "type": "STOCK"}, # 예시 중소형주
    {"code": "017960", "name": "한국카본", "type": "STOCK"},
    {"code": "005380", "name": "현대차", "type": "STOCK"},
    {"code": "058610", "name": "에스피지", "type": "STOCK"},
    {"code": "454910", "name": "두산로보틱스", "type": "STOCK"},
    {"code": "277810", "name": "레인보우로보틱스", "type": "STOCK"},
    {"code": "373220", "name": "LG에너지솔루션", "type": "STOCK"}, 
]

# 기간 설정 (최근 2년)
end_date = datetime.now()
start_date = end_date - timedelta(days=730) 

print(f"📅 데이터 수집 기간: {start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}")

# 폴더 생성
if not os.path.exists('history_data_backtest'):
    os.makedirs('history_data_backtest')

# 데이터 다운로드 및 저장
for item in targets:
    print(f"📥 [{item['name']}] 데이터 다운로드 중...")
    
    # fdr을 통해 데이터 가져오기
    df = fdr.DataReader(item['code'], start_date, end_date)
    
    # 컬럼명 통일 (Backtester가 읽기 좋게)
    # FinanceDataReader는 Open, High, Low, Close, Volume, Change를 반환함
    
    # 파일 저장
    file_path = f"history_data_backtest/{item['code']}.csv"
    df.to_csv(file_path)
    print(f"   ㄴ 저장 완료: {file_path} ({len(df)} rows)")

print("\n✨ 모든 데이터 수집이 완료되었습니다!")