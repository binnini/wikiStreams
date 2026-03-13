# TODO

---

## 완료된 주요 작업

- [x] **아키텍처 경량화 4단계 완료** — AWS t4g.small(2 GiB) 안정 운영 중 *(2026-03-08~12)*
  - Kafka → Redpanda (-802 MiB)
  - ClickHouse → QuestDB (-1,756 MiB)
  - Loki/Alloy 제거 → SLO 지표 QuestDB 이관 (-257 MiB, CPU -57.3%)
  - 전환 후 실측 합산 메모리: **~947 MiB (t4g.small 46%)**
  - 상세 벤치마크: [`docs/ARCH_LIGHTENING_REPORT.md`](ARCH_LIGHTENING_REPORT.md)

- [x] **S3 Datalake** — 일일 Parquet 백업 운영 중 *(2026-03-11)*
  - QuestDB TTL 5일 이후 데이터를 S3에 영구 보관
  - 저장 경로: `s3://{bucket}/events/year=YYYY/month=MM/day=DD/events.parquet`

- [x] **SLO 수립 + 대시보드 + 알림** *(2026-03-06~08)*
  - 11개 SLO 정의·모니터링 중 (A2/A3/P1/P3/P5/P7/R1/D1/D2/CAP1/CAP2)
  - `producer_slo_metrics`, `resource_metrics` QuestDB 테이블로 전부 이관

- [x] **Grafana 대시보드 버그 수정** *(2026-03-12)*
  - `ts as time` 별칭 누락으로 발생한 "time column is missing" 오류 수정
  - Resources Monitor bargauge 0% 표시 버그 수정 (CASE WHEN 피벗 쿼리)

- [x] **포트폴리오 문서 작성** *(2026-03-12)*
  - `docs/PORTFOLIO.md` — 채용 담당자 대상 회고 및 기술 의사결정 기록
  - `docs/evaluation_result/EVALUATION_RESULT_260312.md` — EVALUATION_KITS 기준 평가

- [x] **이상 감지 알림 (Resource Monitor)** — z-score + severity + runbook *(2026-03-11)*
- [x] **일일 트렌드 리포트 (Reporter → Slack)** *(2026-03-01)*
- [x] **CI 파이프라인 이원화** — unit-tests(PR) / integration-tests(main push) *(2026-03-01)*

---

## 미완료 — 우선순위 높음

- [ ] **SLO-D2 목표 재검토**
  - 레이블 보강률 실측: 78~80% 경계 (SLO 목표 ≥80%)
  - 원인: Wikidata 구조적 한계 (~20% Q-ID에 en/ko 레이블 없음)
  - 2026-03-17 이후 `pytest -m slo` 재실행 후 목표값 조정 예정

- [ ] **데이터 처리량 급감 알림**
  - Events/min이 급격히 감소해도 자동 알림 없음 (Grafana 수동 확인만 가능)
  - 방안: Grafana Alerting으로 `producer_slo_metrics.batch_size` 기반 임계값 알림 추가

- [ ] **무중단 배포 안전성**
  - 현재는 `docker compose up -d` 직접 실행. 설정 오류 시 서비스 중단 위험.
  - [ ] 각 서비스에 `healthcheck` + `depends_on: condition: service_healthy` 추가
  - [ ] `scripts/deploy.sh`: build → `pytest tests/unit/` 통과 시에만 `up -d` 실행
  - [ ] 배포 전 `docker tag :latest :stable` 스냅샷 → 문제 시 즉시 롤백

---

## 미완료 — 우선순위 낮음

- [ ] **AsyncIO 리팩토링**
  - 현재 동기식 구조: Wikidata API 호출이 배치 처리를 블로킹.
  - 검토 기준: `batch_processing_seconds` p95 ≥ 1.5s / 캐시 히트율 ≤ 70% / SLO-D2 미달 지속
  - Phase 1 — enricher만 `asyncio.gather` (효과 최대, 리스크 최소)
  - Phase 2 — `asyncio.Queue` 기반 collector + enricher
  - Phase 3 — `aiokafka` + `aiosqlite` 완전 async
  - 현재 규모(~1,000 events/min, 캐시 히트 p5=89%)에서는 불필요. P1 SLO 위반 시 재판단.

- [ ] **CI Smoke/Full E2E 이원화**
  - PR 단계: Smoke Test만 실행 (빠른 피드백)
  - main 머지: Full E2E 실행
  - 현재는 단계 구분 없이 통합 테스트 전체 실행

- [ ] **중복 이벤트 제거**
  - SSE 재연결 시 중복 이벤트 수신 가능 (`Last-Event-ID` 헤더로 부분 완화됨).
  - 검토 방법: Redpanda 메시지 키를 이벤트 고유 ID로 설정, 또는 QuestDB DEDUP 활용.

- [ ] **SQLite 캐시 → 공유 캐시 교체**
  - 현재 SQLite는 Producer 단일 프로세스 전용. scale-out 불가.
  - Producer scale-out이 필요해지는 시점에 Redis 또는 외부 캐시로 교체 검토.

- [ ] **확장성 검증 리포트**
  - k6 또는 Locust로 초당 수천 건 가상 이벤트를 Producer에 주입.
  - Redpanda / QuestDB 처리 한계 측정 및 병목 구간 파악 → `docs/` 하위 리포트 정리.
