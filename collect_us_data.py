import FinanceDataReader as fdr
import pandas as pd
import os
from datetime import datetime, timedelta

# ==========================================
# 🛠️ 설정: 백테스트할 미국 종목들 (티커 입력)
# ==========================================
# 미국은 종목코드 대신 '티커(Ticker)'를 사용합니다.
targets = [
    {"code": "SOXS", "name": "반도체3배_인버스", "type": "ETF"},
    #{"code": "SOXL", "name": "반도체3배_Direxion", "type": "ETF"},
    #{"code": "TSLA", "name": "테슬라", "type": "STOCK"},
    #{"code": "GOOG", "name": "구글", "type": "STOCK"},
    #{"code": "SQQQ", "name": "나스닥3배_인버스", "type": "ETF"},
    #{"code": "SPY",  "name": "S&P500", "type": "ETF"},
]

# 기간 설정 (최근 2년 + 여유분)
# 이동평균선(SMA60) 계산 등을 위해 여유 있게 750일 정도 가져옵니다.
end_date = datetime.now()
start_date = end_date - timedelta(days=750) 

print(f"📅 [US] 데이터 수집 기간: {start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}")

# 폴더 생성
if not os.path.exists('history_data_backtest'):
    os.makedirs('history_data_backtest')

# 데이터 다운로드 및 저장
for item in targets:
    print(f"📥 [{item['name']}({item['code']})] 데이터 다운로드 중...")
    
    try:
        # fdr에 티커(예: 'TQQQ')를 넣으면 야후 파이낸스 등을 통해 미국 데이터를 가져옵니다.
        df = fdr.DataReader(item['code'], start_date, end_date)
        
        if df.empty:
            print(f"   ⚠️ 데이터가 없습니다: {item['code']}")
            continue

        df.index.name = 'Date'

        # 데이터 저장
        # 파일명은 TQQQ.csv, SOXL.csv 처럼 티커로 저장됩니다.
        file_path = f"history_data_backtest/{item['code']}.csv"
        df.to_csv(file_path)
        print(f"   ✅ 저장 완료: {file_path} ({len(df)} rows)")
        
    except Exception as e:
        print(f"   ❌ 에러 발생 ({item['code']}): {e}")

print("\n✨ [US] 모든 데이터 수집이 완료되었습니다!")