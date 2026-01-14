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

# 4. Druid 준비 대기 (Python 사용)
echo "Waiting for Druid Router..."
while true; do
    STATUS=$(python3 -c "import urllib.request; print(urllib.request.urlopen('http://router:8888/status/health').getcode())" 2>/dev/null)
    if [ "$STATUS" == "200" ]; then
        echo "Druid is ready!"
        break
    fi
    echo "Druid is not ready yet... retrying in 5 seconds"
    sleep 5
done

# 5. 데이터소스(DB 연결) 자동 임포트
# YAML 파일에 정의된 설정을 로드합니다.
superset import-datasources -p /app/datasources/druid.yaml

# 6. 서버 실행
/usr/bin/run-server.sh
