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

# 4. 데이터소스(DB 연결) 자동 임포트
# YAML 파일에 정의된 설정을 로드합니다.
superset import-datasources -p /app/datasources/druid.yaml

# 5. 서버 실행
/usr/bin/run-server.sh
