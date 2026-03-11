# TODO

---

## 완료된 주요 작업

- [x] **아키텍처 경량화** — AWS t3.small(2 GiB) 마이그레이션 완료 *(2026-03-08)*
  - Kafka → Redpanda (-802 MiB)
  - ClickHouse → QuestDB (-1,756 MiB)
  - 전환 후 실측 합산 메모리: **~1,446 MiB (t3.small 71%)**
  - 상세 벤치마크: [`docs/ARCH_LIGHTENING_REPORT.md`](ARCH_LIGHTENING_REPORT.md)

- [x] **S3 Datalake** — 일일 Parquet 백업 운영 중 *(2026-03-11)*
  - QuestDB TTL 5일 이후 데이터를 S3에 영구 보관
  - 저장 경로: `s3://{bucket}/events/year=YYYY/month=MM/day=DD/events.parquet`

- [x] **SLO 수립 + 대시보드 + 알림** *(2026-03-06~08)*
- [x] **이상 감지 알림 (Resource Monitor)** — z-score + severity + runbook *(2026-03-11)*
- [x] **일일 트렌드 리포트 (Reporter → Slack)** *(2026-03-01)*
- [x] **CI 파이프라인 이원화** — unit-tests(PR) / integration-tests(main push) *(2026-03-01)*

---

## 미완료 — 우선순위 높음

- [ ] **Loki/Alloy 경량화** *(옵션 선택 대기)*
  - Loki(253 MiB) + Alloy(104 MiB) = 357 MiB. SLI 지표 25개가 Loki `unwrap`에 의존.
  - **Option A** — 스킵 (현재 선택): t3.small 71% → 스왑 1 GiB 추가로 안정 운영 가능
  - **Option B** — Alloy → Promtail 교체: -79 MiB, 설정 변경만 필요
  - **Option C** — QuestDB 직접 메트릭: -357 MiB, SLO 대시보드 전체 재작성 필요

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
  - 현재 규모(18 events/sec, 캐시 히트 93%)에서는 불필요. 일주일 이상 관찰 후 재판단.

- [ ] **중복 이벤트 제거**
  - SSE 재연결 시 중복 이벤트 수신 가능 (`Last-Event-ID` 헤더로 부분 완화됨).
  - 검토 방법: Kafka 메시지 키를 이벤트 고유 ID로 설정, 또는 QuestDB DEDUP 활용.

- [ ] **SQLite 캐시 → 공유 캐시 교체**
  - 현재 SQLite는 Producer 단일 프로세스 전용. scale-out 불가.
  - Producer scale-out이 필요해지는 시점에 Redis 또는 외부 캐시로 교체 검토.

- [ ] **확장성 검증 리포트**
  - k6 또는 Locust로 초당 수천 건 가상 이벤트를 Producer에 주입.
  - Redpanda / QuestDB 처리 한계 측정 및 병목 구간 파악 → `docs/` 하위 리포트 정리.
