# TODO

## 우선순위 높음

- [x] **Dead Letter Queue (DLQ) 도입** *(2026-02-26 부분 완료)*
  - [x] 실패 메시지를 별도 Kafka 토픽(`wikimedia.recentchange.dlq`)으로 라우팅
  - [x] DLQ 메시지에 `error`, `failed_at`, `source_topic`, `retry_count` 메타데이터 포함
  - [x] Grafana Error Monitor에 DLQ Events/min, DLQ Total 패널 추가
  - [x] DLQ 컨슈머 서비스 구성 (재처리 또는 알림) *(2026-02-26 완료)*

- [ ] **입력 데이터 스키마 검증**
  - Wikimedia SSE 이벤트를 Pydantic 모델로 정의
  - 필수 필드 누락 또는 타입 불일치 시 DLQ로 격리
  - Wikidata API 응답도 동일하게 검증

## 우선순위 중간

- [ ] **`collector.py` 리팩토링**
  - 현재 1,137줄로 SSE 연결 관리 / 배치 로직 / 에러 처리가 혼재
  - 역할별로 클래스 또는 모듈 분리 (`SSEClient`, `BatchBuffer`, `RetryPolicy` 등)

- [ ] **AsyncIO 리팩토링**
  - 현재 동기식(Blocking) I/O 구조: Wikidata API 호출이 배치 처리를 블로킹
  - `asyncio` + `httpx` (이미 사용 중) + `aiokafka`로 전환
  - 처리량(Throughput) 및 10초 타임아웃 의존도 개선 기대

- [x] **캐시 TTL 도입** *(2026-02-26 부분 완료)*
  - [x] `CACHE_TTL_SECONDS` 설정 추가 (기본값 86400초 / 24시간)
  - [x] `get_qids_from_cache()`에 TTL 만료 필터링 추가 (lazy expiry)
  - [ ] Wikidata `"missing"` 응답 구분 및 차등 TTL 적용
    - 정상 enrichment 성공: 긴 TTL (예: 30일)
    - `"missing"` 응답 (엔티티 미존재): 짧은 TTL (예: 24시간)

- [ ] **SQLite 캐시를 Redis로 교체**
  - 현재 SQLite는 단일 프로세스에서만 유효 (Producer scale-out 불가)
  - `docker-compose.yml`의 기존 Redis 서비스 활용 (Superset용으로 이미 실행 중)
  - 여러 Producer 인스턴스가 캐시를 공유하게 되어 API 중복 호출 제거

## 우선순위 낮음

- [ ] **CI 파이프라인 이원화**
  - 현재: 모든 테스트(Unit + Integration + E2E)를 PR마다 실행
  - PR 단계: Unit + Integration (Smoke Test)
  - Merge 단계: 전체 E2E
  - 빌드 시간 및 비용 절감

- [ ] **확장성 검증 리포트 작성**
  - `k6` 또는 `Locust`로 초당 수천 건의 가상 이벤트를 Producer에 주입
  - Kafka / Druid 처리 한계(Throughput) 측정 및 병목 구간 파악
  - 결과를 `docs/` 하위에 리포트로 정리

- [ ] **클라우드 배포 (CD 파이프라인)**
  - AWS EC2 또는 ECS에 Docker Compose 스택 배포
  - GitHub Actions → AWS 간단한 CD 파이프라인 구성
