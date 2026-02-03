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
# Druid Router가 준비될 때까지 기다립니다.
DRUID_HOST="router"
DRUID_PORT="8888"
echo "Waiting for Druid at $DRUID_HOST:$DRUID_PORT..."

while ! curl -s "http://$DRUID_HOST:$DRUID_PORT/status/health" | grep "true" > /dev/null; do
  echo "Druid is not ready yet. Retrying in 5 seconds..."
  sleep 5
done

echo "✅ Druid is ready! Importing database connection..."

# 5. 데이터소스(DB 연결) 자동 임포트
# Apache Druid 연결 정보만 임포트합니다.
superset import-datasources -p /app/datasources/druid.yaml

# 6. 서버 실행
echo "🚀 Starting Superset server..."
/usr/bin/run-server.sh
