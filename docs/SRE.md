# WikiStreams SRE 운영 가이드

> 이 문서는 WikiStreams에서 SRE(Site Reliability Engineering) 원칙을 실제로 어떻게 적용하는지 기록합니다.

---

## SRE 문서 구조

| 문서 | 역할 |
|---|---|
| [NFR.md](NFR.md) | 비기능 요구사항 — SLI/SLO 도출의 선행 산출물 |
| [SLI.md](SLI.md) | 서비스 수준 지표 — 측정 방법과 쿼리 정의 |
| [SLO.md](SLO.md) | 서비스 수준 목표 — 수치 목표와 에러 버짓 |
| [SLA.md](SLA.md) | 서비스 수준 협약 — 책임 범위와 위반 처리 |

---

## 적용된 SRE 실천 원칙

### 1. SLO 기반 운영

5개 영역(가용성·성능·신뢰성·데이터 품질·용량)에 걸쳐 SLO를 정의하고, Grafana SLO 대시보드로 30일 롤링 윈도우 기준 실시간 추적합니다.

주요 SLO:

| SLI | 목표 | 측정 방법 |
|---|---|---|
| 데이터 신선도 (D1) | lag ≤ 30초 | QuestDB 최신 이벤트 타임스탬프 |
| 레이블 보강률 (D2) | ≥ 80% | Q-ID 중 레이블 있는 비율 |
| 처리량 (P5) | ≥ 800 events/min | QuestDB 1분 집계 p5 |
| 캐시 히트율 (P7) | ≥ 80% | Loki 로그 파싱 |
| DLQ 비율 (R1) | ≤ 1% | Loki 로그 파싱 |

### 2. 에러 버짓

SLO 목표값으로부터 허용 위반 시간/횟수를 산출합니다. 에러 버짓 소진 시 신규 기능 배포를 보류하고 안정화에 집중합니다.

예시: SLI-D1 (신선도, 목표 99.5%)
- 30일 에러 버짓 = 30일 × 24h × 60min × 0.5% = **216분**

### 3. 알림 규칙 (Grafana Alert Rules)

`monitoring/grafana-alert-rules.yaml`에 6개 알림 규칙이 정의되어 있습니다:

| 규칙 | 조건 | 채널 |
|---|---|---|
| slo-d1-freshness | lag > 30s, for: 2m | Slack |
| slo-d1-freshness-critical | lag > 120s, for: 1m | Slack |
| slo-a3-reporter | 1시간 내 Reporter 발송 없음 (09-10시 KST) | Slack |
| slo-r1-dlq | DLQ 비율 > 1%, for: 3m | Slack |
| slo-p7-cache | 캐시 히트율 < 80%, for: 10m | Slack |
| slo-cap1-questdb-mem | QuestDB 메모리 > 80%, for: 5m | Slack (critical) |

### 4. 이상 감지 (Anomaly Detection)

`resource-monitor` 서비스가 10초 간격으로 컨테이너 메트릭을 수집하고, z-score 기반으로 이상을 감지합니다.

- **Baseline**: SQLite에 컨테이너 × 시간대(hour) 버킷으로 EMA + Welford online variance 저장
- **감지 조건**: z-score > 2.5 AND 절댓값 임계 초과 (노이즈 억제)
- **Severity**: warning (z < 4.0) / critical (z ≥ 4.0 또는 절댓값 임계 초과)
- **Cooldown**: 동일 컨테이너·메트릭 기준 1시간 중복 알림 억제

### 5. Runbook

Slack 알림 메시지에 컨테이너별 점검 명령어가 포함됩니다:

```
# questdb mem_pct 알림 시
docker stats questdb --no-stream
docker exec questdb curl -s http://localhost:9000/metrics | grep memory
```

### 6. Toil 자동화

반복 수동 작업을 코드로 대체한 사례:

| 자동화 항목 | 구현 방법 |
|---|---|
| 일일 트렌드 리포트 | `reporter` 서비스 스케줄러 (09:00 KST) |
| S3 데이터 백업 | `s3-exporter` 데몬 (01:00 UTC) |
| 이상 감지 알림 | `resource-monitor` 서비스 |
| 서비스 자동 시작 | launchd plist (`scripts/`) |

---

## 인시던트 대응 절차

### 1. 알림 수신 시

1. Slack 알림의 severity(warning/critical)와 runbook 확인
2. Grafana SLO 대시보드에서 현재 SLI 수치 확인
3. Loki Error Monitor에서 최근 에러 로그 조회

### 2. 주요 장애 유형별 대응

**데이터 신선도 lag 급증 (SLI-D1)**
```bash
docker compose logs -f producer      # SSE 연결 상태 확인
docker compose logs -f questdb-consumer  # 적재 오류 확인
docker stats redpanda --no-stream    # Redpanda 리소스 확인
```

**QuestDB 메모리 과다 (SLI-CAP1)**
```bash
docker stats questdb --no-stream
# TTL 만료로 자연 감소 대기 (5일 TTL)
# 즉시 해소 필요 시: docker compose restart questdb
```

**Producer 처리량 급감 (SLI-P5)**
```bash
docker compose logs -f producer | grep "BatchProcessed"
# Wikidata API 오류 시 캐시 히트율 확인
docker compose logs -f producer | grep "cache_hit"
```

### 3. 사후 검토

장애 해소 후 `docs/DEV_LOG.md`에 원인·대응·재발 방지 내용을 기록합니다.

---

## 용량 계획

| 컴포넌트 | 실측 메모리 | 상한 |
|---|---|---|
| Redpanda | ~387 MiB | — |
| QuestDB | ~600 MiB | mem_limit 1100m |
| Grafana | ~100 MiB | — |
| Loki + Alloy | ~357 MiB | — |
| Producer + Reporter + resource-monitor | ~50 MiB | — |
| **합산** | **~1,494 MiB** | **t3.small 2 GiB의 73%** |

QuestDB는 TTL 5일 + `mem_limit: 1100m` cgroup 압력으로 working set 상한을 제어합니다. 메모리 증가 추이가 지속될 경우 TTL을 3일로 단축하거나 스왑 1 GiB를 추가합니다.
