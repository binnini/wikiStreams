#!/bin/bash

# 1. 관리자 계정 생성
superset fab create-admin \
    --username admin \
    --firstname Superset \
    --lastname Admin \
    --email admin@superset.com \
    --password admin || echo "Admin user already exists, skipping..."

# 2. 메타데이터 DB 업그레이드
superset db upgrade

# 3. 기본 역할 및 권한 설정
superset init

# 4. Druid 연결 대기 (Wait for Druid)
# Druid Router가 준비될 때까지 기다립니다. (Python 사용)
echo "Waiting for Druid Router..."
python3 -c '
import urllib.request
import time
import sys

url = "http://router:8888/status/health"
timeout = 300  # 5 minutes
start_time = time.time()

while time.time() - start_time < timeout:
    try:
        with urllib.request.urlopen(url) as response:
            if response.getcode() == 200:
                print("✅ Druid is ready!")
                sys.exit(0)
    except Exception as e:
        print(f"⏳ Druid not ready yet: {e}")
        time.sleep(5)

print("❌ Timeout waiting for Druid")
sys.exit(1)
'

echo "Importing database connection..."

# 5. 데이터소스(DB 연결) 자동 임포트
# Apache Druid 연결 정보만 임포트합니다.
superset import-datasources -p /app/datasources/druid.yaml

# 6. 대시보드 및 데이터셋 임포트
echo "Importing dashboards and datasets..."
# 데이터셋이 정의된 YAML 파일이 있다면 임포트
if [ -f "/app/datasources/datasets/Druid/wikimedia_recentchange.yaml" ]; then
    superset import-datasources -p /app/datasources/datasets/Druid/wikimedia_recentchange.yaml
fi

# 대시보드 임포트
if [ -f "/app/dashboards/wikimedia_dashboard.zip" ]; then
    superset import-dashboards -p /app/dashboards/wikimedia_dashboard.zip
fi

# 7. 서버 실행
echo "🚀 Starting Superset server..."
/usr/bin/run-server.sh
