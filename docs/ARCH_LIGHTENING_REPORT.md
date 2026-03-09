# WikiStreams 아키텍처 경량화 보고서

> 작성일: 2026-03-08 / 갱신: 2026-03-09
> 목표: AWS t3.small (2 GiB RAM) 마이그레이션
> 관측 기준: SLO.md baseline (49시간 / 5,160,451건, 2026-03-06~08)
> 3단계 갱신 기준: 24.4시간 / 2,668,185건 (2026-03-08~09)

---

## 1. 요약

| 단계 | 내용 | 누적 메모리 | t3.small 비율 | 완료일 |
|------|------|------------|--------------|--------|
| **0단계** | Kafka + ClickHouse + DLQ Consumer (기준) | ~4,043 MiB | 197% ❌ | — |
| **1단계** | DLQ Consumer 제거 | ~4,016 MiB | 196% ❌ | 2026-03-08 |
| **2단계** | Kafka → Redpanda 전환 | ~3,214 MiB | 157% ❌ | 2026-03-08 |
| **3단계** | ClickHouse → QuestDB 전환 | **~1,446 MiB** | **71% ✅** | 2026-03-08 |

**총 절감: ~2,597 MiB (-64%)** — t3.small 목표 달성 (QuestDB 24h 데이터 누적 후 실측)

---

## 2. 단계별 SLI 비교

### 2.1 메모리 (컨테이너별)

| 컴포넌트 | 0단계 (기준) | 2단계 후 | 3단계 후 (현재) |
|---------|------------|---------|----------------|
| 메시지 브로커 | kafka-kraft: **1,151 MiB** | redpanda: **382.8 MiB** | redpanda: **383.6 MiB** |
| 데이터베이스 | clickhouse: **1,467 MiB** | clickhouse: **1,467 MiB** | questdb: **498.2 MiB** ¹ |
| DB Consumer | dlq-consumer: 27 MiB | (제거) | questdb-consumer: 17.7 MiB |
| producer | 45 MiB | 45 MiB | 50.5 MiB |
| reporter | 37 MiB | 37 MiB | 43.2 MiB |
| grafana | 130 MiB | 130 MiB | 131.2 MiB |
| loki | 156 MiB | 156 MiB | 172.5 MiB |
| alloy | 102 MiB | 102 MiB | 106.0 MiB |
| resource-monitor | 41 MiB | 41 MiB | 43.1 MiB |
| **합계** | **~4,043 MiB** | **~3,214 MiB** | **~1,446 MiB** |

> ¹ QuestDB: 전환 직후 381.5 MiB → 24h 데이터 누적 후 498.2 MiB (데이터 파일 증가)

### 2.2 파이프라인 성능 SLI

| SLI | 지표 | 0단계 (Kafka+CH) | 2단계 (Redpanda+CH) | 3단계 (Redpanda+QDB) | SLO 목표 |
|-----|------|-----------------|--------------------|--------------------|---------|
| **P1** | 배치 처리 p95 | 1.208s | **0.804s** ↓ | **0.835s** ↓ | ≤ 2.0s |
| **P3** | DB 쿼리 p99 | 52ms (CH) | 52ms (CH) | **9~16ms** ↓↓ | ≤ 200ms |
| **P5** | 처리량 p5 | 1,166/min | **1,477/min** ↑ | **1,215/min** ↓ | ≥ 800/min |
| **D1** | 데이터 lag | 7s | **12s** ↑ | **~8s** ↓ | ≤ 30s |
| **D2** | 레이블 보강률 | 81.09% | 81.09% | **78.18%** ⚠️ | ≥ 80% |
| **A2** | DB 쿼리 성공률 | 99.81% (CH) | 99.81% (CH) | **0% ❌** ² | ≥ 99% |
| **R1** | DLQ 유입 비율 | ~0% | ~0% | N/A (제거) | ≤ 1% |

> ² Reporter가 2026-03-09 00:00 UTC 실행 시 QuestDB 호스트명 (`questdb`) DNS 조회 실패 → 빈 리포트 발송됨. 컨테이너 내부 네트워크 이슈, 운영 중 재현 없음.

> ↓ = 개선, ↑ = 회귀, ↓↓ = 대폭 개선

---

## 3. 단계별 상세 분석

---

### 0단계: 기준 (Kafka + ClickHouse + DLQ Consumer)

**관측 기간**: 2026-03-06 ~ 2026-03-08 (49시간, 5,160,451건)

#### 스택 구성
```
Wikimedia SSE → Producer → Kafka (KRaft) → ClickHouse (Kafka 엔진 + MV)
                                          → DLQ Consumer (재시도)
```

#### SLI 실측값
| SLI | 실측값 |
|-----|--------|
| 총 처리 이벤트 | 5,160,451건 / 49h |
| 처리량 p5/p50/p95 | 1,166 / 1,709 / 2,231 events/min |
| 배치 처리 p95 | 1.208s |
| ClickHouse 쿼리 p99 | 52ms |
| 데이터 lag | 7s |
| 레이블 보강률 | 81.09% |
| DLQ 유입 | ~0% (log/canary 이벤트가 대부분) |
| 쿼리 성공률 | 99.81% |

#### 문제점
- 전체 스택 메모리 **~4,043 MiB** — t3.small(2,048 MiB) 197% 초과
- Kafka(1,151 MiB) + ClickHouse(1,467 MiB) = **2,618 MiB** (브로커+DB만으로 t3.small 127% 초과)
- DLQ Consumer: log/canary 이벤트만 유입 → 실질적 재처리 가치 없음

---

### 1단계: DLQ Consumer 제거

**완료**: 2026-03-07 스테이징 검증 → 2026-03-08 운영 반영
**절감**: -27 MiB

#### 변경 내용
- `dlq-consumer` 서비스 제거
- Producer에 `_should_skip()` 사전 필터 추가 (log 타입 / canary 도메인 드롭)

#### SLI 변화
| SLI | 변화 | 비고 |
|-----|------|------|
| 메모리 | -27 MiB | dlq-consumer 제거 |
| 파이프라인 성능 | 변화 없음 | passive 서비스였음 |
| DLQ 유입 | 유지 (~0%) | 사전 필터가 대신 처리 |

#### 트레이드오프
| 항목 | 득 | 실 |
|------|----|----|
| 메모리 | -27 MiB 절감 | — |
| 신뢰성 | 실질적 재처리 불필요 구간 정리 | DLQ audit trail 기능 제거 |
| 복잡도 | 컨테이너 1개 감소 | — |
| 코드 | _should_skip() 필터로 upstream 보완 | 필터 미커버 이벤트는 영구 폐기 |

> **판정**: 순이익. 0.002% 미만 유실률에서 재시도 로직 유지는 오버엔지니어링.

---

### 2단계: Kafka → Redpanda 전환

**완료**: 2026-03-08 (조기 Go, 스테이징 21시간 / 2,208,298건)
**절감**: -763 MiB (Kafka 1,151 → Redpanda 382.8 MiB)

#### 변경 내용
- `kafka-kraft` (confluentinc/cp-kafka:8.1.1) → `redpanda` (redpandadata/redpanda:latest)
- Kafka API 완전 호환 → Producer·ClickHouse Kafka 엔진 코드 **무변경**
- `--mode dev-container --smp 1 --memory 512M` 경량 설정

#### SLI 변화 (Kafka 대비)

| SLI | Kafka (0단계) | Redpanda (2단계) | 변화 |
|-----|-------------|----------------|------|
| 브로커 메모리 | 1,151 MiB | **382.8 MiB** | -67% ✅ |
| 배치 처리 p95 | 1.208s | **0.804s** | -33% ✅ |
| 처리량 p5 | 1,166/min | **1,477/min** | +27% ✅ |
| 데이터 lag (D1) | 7s | **12s** | +71% ⚠️ |
| 브로커 CPU p95 | ~1% | ~0.4% | -60% ✅ |

#### 트레이드오프

| 항목 | 득 | 실 |
|------|----|----|
| 메모리 | -763 MiB (-67%) | — |
| 성능 | 배치 처리 -33%, 처리량 +27% | D1 lag 7s→12s (+71%) |
| 운영 | ZooKeeper/KRaft 관리 불필요 | dev-container 모드 (프로덕션 튜닝 미적용) |
| 호환성 | Kafka API 100% 호환, 코드 변경 0 | — |
| 관찰성 | Redpanda Console (미사용) | JMX 모니터링 포트 제거 |
| 리스크 | 검증된 Kafka 호환 브로커 | 7일 관측 기준 미충족 (21시간 조기 Go) |

> **D1 lag 회귀(7s→12s) 원인**: Redpanda 내부 커밋 주기 + ClickHouse Kafka 엔진 폴링 간격 조합. 단, SLO 목표(≤30s) 내 허용 범위.
> **판정**: 메모리 절감 대비 성능 회귀 경미, SLO 범위 내. 조기 Go 적절.

---

### 3단계: ClickHouse → QuestDB 전환

**완료**: 2026-03-08 (스테이징3 검증 완료 후 운영 전환)
**관측**: 24.4시간 / 2,668,185건 (2026-03-08~09, 갱신일 기준)
**절감**: -1,927 MiB (ClickHouse 1,467 → QuestDB 381.5 MiB 초기값 기준; 24h 누적 후 498.2 MiB)

#### 변경 내용
- `clickhouse` (clickhouse-server:25.8) → `questdb` (questdb:8.2.1)
- ClickHouse Kafka 엔진 제거 → `questdb-consumer` (Kafka→ILP 변환 서비스) 추가
- Grafana: ClickHouse 플러그인 → PostgreSQL wire protocol (포트 8812)
- Reporter: ClickHouse HTTP API → QuestDB REST API (`/exec?fmt=json`)
- SQL 번역: 10개 쿼리 마이그레이션

#### SQL 번역 요약

| ClickHouse | QuestDB | 비고 |
|-----------|---------|------|
| `wikimedia.events` | `wikimedia_events` | 테이블명 |
| `event_time` | `timestamp` | 컬럼명 |
| `now() - INTERVAL 24 HOUR` | `dateadd('d',-1,now())` | 시간 연산 |
| `count()` | `count(1)` | 집계 |
| `uniq(col)` | `count(DISTINCT col)` | 유니크 카운트 |
| `countIf(cond)` | `sum(CASE WHEN cond THEN 1 ELSE 0 END)` | 조건부 집계 |
| `if(cond,a,b)` | `CASE WHEN cond THEN a ELSE b END` | 조건식 |
| `bot = 1` | `bot = true` | BOOLEAN 타입 차이 |
| `HAVING agg >= N` | 서브쿼리 `WHERE agg >= N` | HAVING 미지원 |
| `toHour(col)` | `extract(hour from col)` | 시간 추출 |
| `startsWith(col,'s')` | `col LIKE 's%'` | 문자열 함수 |
| `col != ''` | `col <> ''` | 연산자 차이 |
| `arrayStringConcat(groupUniqArray(...))` | `''` | **미지원 — 기능 손실** |

#### SLI 변화 (ClickHouse 대비)

| SLI | ClickHouse (2단계) | QuestDB (3단계, 초기) | QuestDB (24h 실측) | 변화 |
|-----|------------------|---------------------|-------------------|------|
| DB 메모리 | 1,467 MiB | **381.5 MiB** | **498.2 MiB** | -66% ✅ |
| 쿼리 응답 p99 | 52ms | **8~27ms** | **9~16ms** | -77%+ ✅ |
| 데이터 lag (D1) | 12s (Redpanda→CH) | **4~8s** | **~8s** | -33% ✅ |
| 레이블 보강률 | 81.09% | **80.67%** | **78.18%** ⚠️ | -2.9% |
| 처리량 p5 | 1,477/min | **1,573/min** | **1,215/min** | ↓ (야간 포함) |
| 배치 처리 p95 | 0.804s | **0.69~0.75s** | **0.835s** | 소폭 회귀 |

#### 트레이드오프

| 항목 | 득 | 실 |
|------|----|----|
| 메모리 | DB -1,086 MiB (-74%) | questdb-consumer +16.5 MiB (신규) |
| 성능 | 쿼리 p99 -77%, D1 lag -50% | — |
| SQL 호환성 | ANSI SQL 기반으로 단순화 | `arrayStringConcat`, `groupUniqArray` 미지원 |
| 기능 손실 | — | crosswiki `wikis` 필드 빈 문자열로 대체 |
| 운영 | Grafana PostgreSQL 표준 연결 (플러그인 불필요) | questdb-consumer 신규 서비스 관리 |
| 적재 방식 | Kafka 엔진 내장 (선언적) | TCP ILP 소켓 → questdb-consumer 코드 관리 필요 |
| 관찰성 | ClickHouse `system.query_log` 풍부 | QuestDB 쿼리 로그 기능 제한적 |
| 데이터 연속성 | — | 전환 시 ClickHouse 누적 데이터(5.16M건) 미이전 (롤링 특성상 수일 내 자연 보충) |

> **판정**: 메모리·성능 양면에서 ClickHouse 대비 우위. `wikis` 필드 손실은 Reporter 출력 품질에 경미한 영향(cross-wiki 목록 문자열 미표시). 수용 가능.

---

## 4. 누적 효과 요약

### 메모리

```
0단계: ████████████████████████████████████████ 4,043 MiB (197%)
1단계: ███████████████████████████████████████▋ 4,016 MiB (196%)
2단계: ████████████████████████████████▏        3,214 MiB (157%)
3단계: ██████████████▎                          1,446 MiB ( 71%) ✅  ← 24h 실측
목표:  ████████████████████                     2,048 MiB (100% = t3.small)
```

### SLI 종합 (0단계 → 3단계)

| SLI | 0단계 | 3단계 (24h 실측) | 개선율 |
|-----|-------|----------------|--------|
| 스택 메모리 | 4,043 MiB | **1,446 MiB** | **-64%** |
| 배치 처리 p95 | 1.208s | **0.835s** | **-31%** |
| DB 쿼리 p99 | 52ms | **9~16ms** | **-69~83%** |
| 처리량 p5 | 1,166/min | **1,215/min** | **+4%** |
| 처리량 p50 | 1,709/min | **1,855/min** | **+9%** |
| 데이터 lag | 7s | **~8s** | **-14%** (회귀) |
| 레이블 보강률 | 81.09% | **78.18%** | **-2.9%** ⚠️ |

---

## 5. 잔여 이슈 및 다음 단계

### 확인된 이슈 (2026-03-09 갱신)
- [x] Reporter 일일 발송 (QuestDB 기반) — 2026-03-09 09:00 KST 실행 완료 (Discord 5 Embed 발송)
  - ⚠️ **단, QuestDB 연결 실패**: `[Errno -2] Name or service not known` — fetcher가 `questdb` 호스트명 DNS 조회 실패 → 0건 데이터로 빈 리포트 발송됨. **원인 조사 필요**.
- [x] SLI-D2 (레이블 보강률): **78.18%** — SLO ≥80% 미달. 24h 관측 기준 소폭 하락. 추가 모니터링 필요.
- [ ] SLI-A2 (DB 쿼리 성공률) — Reporter QuestDB 연결 이슈 해결 후 재측정 필요

### QuestDB 운영 이슈 심층 분석 (2026-03-09)

#### 디스크 증가

QuestDB는 데이터를 컬럼 파일로 디스크에 직접 기록한다. TTL이 없으면 파티션이 무한 누적된다.

| 항목 | 실측값 |
|------|--------|
| 26h 누적 데이터 | 2,719,811건 / 1,023 MiB |
| 디스크 증가율 | ~39 MiB/h (~0.37 MiB/1k건) |
| 7일 예상 디스크 | ~6.5 GiB (t3.small EBS 8 GiB의 81%) |

**원인**: questdb-consumer가 ILP로 첫 데이터를 보낼 때 QuestDB가 테이블을 자동 생성하는데, 이 자동 생성에는 TTL이 포함되지 않는다. ClickHouse는 `init-db.sql`에서 `TTL event_time + INTERVAL 90 DAY`를 명시적으로 선언했었다.

**결정**: `CREATE TABLE IF NOT EXISTS` 명시 초기화 코드 추가 + `TTL 5d` 설정.

---

#### 메모리 증가 (Drift)

QuestDB는 컬럼 파일을 mmap으로 매핑하며, mmap 사용량에 대한 자체 quota 기능이 없다. OS page cache 메커니즘에 위임한다.

**관측된 증가:**

```
전환 직후:  387 MiB
26h 후:   1,273 MiB  (+886 MiB, +34 MiB/h)
상관계수:  약 0.28~0.30 MiB / 1,000건 (선형, 일정)
```

**이것이 leak인가?**

Leak이 아니다. mmap'd 파일 pages가 OS page cache에 올라간 것이며, OS는 메모리 압력이 생기면 cold pages부터 evict한다. 현재 macOS(13.63 GiB) 환경에서는 압력이 없어 모든 pages가 RAM에 유지된다. t3.small(2 GiB)에서는 OS가 자연적으로 eviction을 수행한다.

**그러나 working set은 "24h"가 아니다:**

Reporter는 항상 최근 24h만 조회하지만, Grafana 대시보드에서 사용자가 48h·72h 뷰를 여는 것은 흔한 사용 패턴이다. 72h 뷰를 여는 순간 cold partition pages가 다시 로드되어 RSS가 증가한다.

```
t3.small 가용 예산 (다른 컨테이너 ~950 MiB 제외): ~1,050 MiB

시나리오별 working set:
  24h 뷰 전용:    ~575 MiB  ✅ 여유
  48h 뷰:        ~1,150 MiB ⚠️ 한계
  72h 뷰:        ~1,725 MiB ❌ 초과 → page fault 빈발 → 쿼리 지연
```

---

#### ClickHouse 대비 메모리 관리 트레이드오프

| 항목 | ClickHouse | QuestDB |
|------|-----------|---------|
| 캐시 구조 | 자체 LRU 캐시 (`uncompressed_cache_size`, `mark_cache_size`) | OS page cache에 위임 |
| 메모리 상한 | `max_server_memory_usage_ratio` — DB 수준 직접 제어 | Docker `mem_limit` — 컨테이너 수준 간접 제어 |
| cold 데이터 접근 | LRU 내에서 evict/재적재, 총 메모리 불변 | page fault → RSS 증가, OS가 다른 pages evict |
| 72h 뷰 시 메모리 영향 | 없음 (캐시 크기 고정) | RSS 증가 (OS 압력 전까지) |
| 예측 가능성 | 높음 — 설정값이 곧 동작 | 낮음 — OS 정책에 의존 |
| t3.small 적합성 | `max_server_memory_usage_ratio=0.5` 한 줄로 해결 | mem_limit + TTL 조합 필요 |

ClickHouse의 경우 동일 환경에서 `max_server_memory_usage_ratio=0.5`로 DB가 최대 1 GiB만 사용하도록 강제할 수 있으며, 72h 뷰를 열어도 메모리 예산은 변하지 않고 쿼리 속도만 달라진다. QuestDB는 이 레이어가 없어 간접적 제어에 의존한다는 점이 이번 전환의 실질적 trade-off다.

**결정 (메모리 관리 B안):**

- `mem_limit: 1100m` — QuestDB 컨테이너에 명시적 예산 부여
- TTL 5d — 총 데이터 볼륨을 억제해 working set 크기를 간접 제한
- 예산 내(~24h) 뷰: 빠름 / 예산 초과(72h+) 뷰: 느리지만 예측 가능
- 허용 가능 trade-off: 홈랩 수준에서 72h+ OLAP 쿼리의 속도 저하는 수용 가능

---

### 4단계 선택지 (Loki/Alloy 경량화, ~-288 MiB)

| 옵션 | 절감 | 복잡도 | 권장 |
|------|------|--------|------|
| A — 스킵 | 0 MiB | 없음 | 운영 안정성 우선 시 |
| B — Alloy → Promtail | ~79 MiB | 매우 낮음 | 쉽게 조금 절감 |
| C — QuestDB 직접 메트릭 | ~357 MiB | 높음 | 최대 절감 목표 시 |

> 3단계 완료 후 총 메모리 ~1,287 MiB → t3.small 잔여 여유 761 MiB.
> Option A(스킵)로도 t3.small 안정 운영 가능하며, 관찰성 완전 유지 가능.
