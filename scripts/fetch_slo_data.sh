#!/usr/bin/env bash
# WikiStreams SLO 데이터 수집 + 로컬 다운로드 자동화
#
# 사용법:
#   ./scripts/fetch_slo_data.sh           # 기본 (최근 5일)
#   ./scripts/fetch_slo_data.sh --days 3  # 최근 3일
#   ./scripts/fetch_slo_data.sh --output-dir /tmp/slo  # 출력 디렉터리 지정

set -e

REMOTE_HOST="wikistreams"
REMOTE_DIR="~/wikiStreams"
REMOTE_EXPORT_DIR="$REMOTE_DIR/slo_export"
LOCAL_EXPORT_DIR="./slo_export"
EXTRA_ARGS="$@"

echo "🚀 WikiStreams SLO 데이터 수집 시작"
echo "   원격 서버: $REMOTE_HOST ($REMOTE_DIR)"
echo ""

# 1. 원격 서버에서 export 스크립트 실행
echo "▶ [1/2] 원격 서버에서 데이터 수집 중..."
ssh "$REMOTE_HOST" "cd $REMOTE_DIR && python3 scripts/export_slo_data.py $EXTRA_ARGS"

# 2. 로컬로 다운로드
echo ""
echo "▶ [2/2] 로컬로 다운로드 중..."
mkdir -p "$LOCAL_EXPORT_DIR"
scp -r "$REMOTE_HOST:$REMOTE_EXPORT_DIR/" "$LOCAL_EXPORT_DIR"

echo ""
echo "✅ 완료! 저장 위치: $LOCAL_EXPORT_DIR"
ls -lh "$LOCAL_EXPORT_DIR"
