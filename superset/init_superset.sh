#!/bin/bash

# 1. 관리자 계정 생성
superset fab create-admin \
    --username admin \
    --firstname Superset \
    --lastname Admin \
    --email admin@superset.com \
    --password admin

# 2. 메타데이터 DB 업그레이드
superset db upgrade

# 3. 기본 역할 및 권한 설정
superset init

# 4. 서버 실행
/usr/bin/run-server.sh
