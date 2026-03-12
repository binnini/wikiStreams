# WikiStreams 프로젝트 회고 및 포트폴리오

> **기간**: 2026년 2월 ~ 현재 (진행 중)
> **형태**: 개인 홈랩 프로젝트 (사이드 프로젝트)
> **GitHub**: https://github.com/puding-development/wikiStreams

---

## 한 줄 요약

> 월 $15 예산(AWS t4g.small)으로 분당 ~1,000건의 실시간 위키미디어 편집 이벤트를 수집·분석하는 데이터 파이프라인을 설계·운영하며, 4단계의 아키텍처 개선을 통해 스택 메모리를 77% 절감했습니다.

---

## 왜 만들었나

기술적 관심사에서 시작했습니다. "현업 수준의 스트리밍 파이프라인을 최소 비용으로 혼자 운영할 수 있을까?"라는 질문에 답하고 싶었습니다.

구체적인 목표는 세 가지였습니다:

1. **카파 아키텍처**를 실제로 구현하고 운영하며 이해하기
2. **SLO/SLI 기반 운영**을 경험하기 (정의만 아는 것과 운영해보는 것의 차이)
3. **제약 조건 속 의사결정** — 클라우드 비용이 현실이 될 때 어떤 트레이드오프를 선택하는지

---

## 전체 아키텍처

```
Wikimedia SSE Stream
  → Producer (Python)        # 이벤트 수집 + Wikidata 레이블 보강 (SQLite 캐시)
  → Redpanda (Kafka 호환)     # 메시지 버스
  → QuestDB                  # 시계열 DB (TTL 5일)
  → Grafana                  # 대시보드 + SLO 모니터링 + 알림
  → Reporter (Python)        # 매일 09:00 KST Claude Haiku → Slack 리포트
  → S3 Exporter              # 매일 01:00 UTC Parquet → S3 Datalake
```

모든 인프라는 Docker Compose로 코드로 관리(IaC)하며, AWS EC2 t4g.small 단일 호스트에서 운영합니다.

---

## 핵심 성과 (숫자)

| 항목 | Before (초기) | After (현재) | 개선율 |
|---|---|---|---|
| 스택 전체 메모리 | 4,043 MiB | **947 MiB** | **-77%** |
| Swap 사용량 | ~700 MiB (OOM 위험) | **205 MiB** | **-71%** |
| QuestDB 쿼리 p99 | 52ms (ClickHouse) | **9~16ms** | **-83%** |
| 배치 처리 p95 | 1.208s | **0.723s** | **-40%** |
| 메시지 브로커 메모리 | 1,151 MiB (Kafka) | **288 MiB** (Redpanda) | **-75%** |
| 월 운영비 | t4g.medium $27 | **t4g.small $15** | **-44%** |
| 단위 테스트 | 0개 | **276개** | — |
| SLO 정의 | 없음 | **11개** 모니터링 중 | — |

---

## 아키텍처 의사결정 4단계

이 프로젝트에서 가장 많이 배운 부분은 "무엇을 만들었는가"보다 "왜 그것을 선택했는가"입니다.

---

### 결정 1 — Kafka → Redpanda

**맥락**
초기 Kafka(JVM) + ClickHouse 스택이 t4g.small 2GiB RAM의 197%를 사용했습니다. OOM이 반복 발생하며 실질적으로 운영이 불가능한 상태였습니다.

**고려한 대안**
- Kafka JVM 힙 축소 튜닝 → 처리량 저하, 근본 해결 아님
- NATS → Kafka API 비호환, 코드 전면 수정 필요
- Redpanda → Kafka API 완전 호환, Rust 구현체

**선택 근거**
코드 변경 0줄로 전환 가능하다는 점이 결정적이었습니다. 실제로 `docker-compose.yml`에서 이미지 하나만 교체했습니다.

**측정 결과** (30분 구간 × 3, N=30,000 메시지)

| 지표 | Kafka | Redpanda | 변화 |
|---|---|---|---|
| RSS 평균 | 510 MiB | **316 MiB** | -38% |
| RSS 장기 패턴 | 선형 증가 (OOM 위험) | **수평 고정** | — |
| p999 latency (운영 부하) | 6.3ms | **3.9ms** | -38% |
| p999 latency (2.8× 부하) | **13ms** (GC pause) | 3.8ms | -71% |
| 재시작 복구 시간 avg | 4.1s | **1.9s** | -54% |

**트레이드오프 수용**
Kafka의 20년 생태계와 운영 성숙도를 포기했습니다. 홈랩 규모에서는 실질적 차이가 없다고 판단했습니다.

---

### 결정 2 — ClickHouse → QuestDB

**맥락**
Redpanda 전환으로도 ClickHouse(1,467 MiB)가 여전히 RAM의 71%를 단독으로 차지했습니다. 또한 ClickHouse는 Kafka 엔진으로 직접 소비하는 구조여서 유연성이 낮았습니다.

**고려한 대안**
- ClickHouse 메모리 제한 (`max_server_memory_usage_ratio=0.5`) → 쿼리 성능 저하 감수
- TimescaleDB → PostgreSQL 기반, 익숙하지만 메모리 절감 효과 불확실
- QuestDB → 시계열 특화, ILP(InfluxDB Line Protocol), 메모리 절감 기대

**선택 근거와 실제 측정**

벤치마크를 먼저 돌렸습니다. 5일치 합성 데이터(~780만 건)를 주입하고 Reporter 실제 쿼리 3종으로 비교했습니다.

| 조건 | ClickHouse | QuestDB |
|---|---|---|
| warm p50 (Q3 GROUP BY) | 0.079s | **0.012s** (7× 빠름) |
| cold p95 (Q3 GROUP BY) | 0.117s | **3.572s** (30× 느림) |
| 메모리 RSS | 1,467 MiB | **381 MiB** (-74%) |

**예상치 못한 발견**
QuestDB는 OS page cache를 직접 활용하는 mmap 기반이라, warm 상태에서는 ClickHouse보다 훨씬 빠르지만 cold read 시 page fault spike가 발생합니다. AWS EBS에서 cold p95를 보정하면 이론상 ~82초입니다.

**트레이드오프 수용 근거**
Reporter는 하루 1회 실행이고, Grafana 조회 빈도가 낮아 대부분의 시간 page cache가 warm 상태를 유지합니다. 홈랩 수준에서 cold spike는 수용 가능한 트레이드오프라고 판단했습니다.

---

### 결정 3 — SLO 기반 운영 체계 수립

**맥락**
아키텍처 전환이 완료된 시점에서 "이 시스템이 잘 동작하고 있는가"를 판단하는 기준이 없었습니다. 느낌이 아닌 숫자로 판단하고 싶었습니다.

**구현한 것**

11개 SLO 항목을 정의하고 QuestDB + Grafana 기반 대시보드를 구축했습니다.

| 영역 | SLO | 목표 | 현재 |
|---|---|---|---|
| 성능 | P1 배치 처리 p95 | ≤ 2s | **0.72s ✅** |
| 성능 | P3 쿼리 응답 p99 | ≤ 200ms | **4~30ms ✅** |
| 성능 | P5 처리량 | ≥ 800/min | **~1,000/min ✅** |
| 성능 | P7 캐시 히트율 | ≥ 80% | **94% ✅** |
| 신뢰성 | R1 DLQ 비율 | ≤ 1% | **~0% ✅** |
| 데이터 | D1 데이터 lag | ≤ 30s | **~9s ✅** |
| 데이터 | D2 레이블 보강률 | ≥ 80% | **79~88% ⚠️** |
| 가용성 | A3 Reporter 발송 | 월 ≥ 27회 | **정상 ✅** |

**D2 이슈에서 배운 것**
레이블 보강률이 목표 80%를 간헐적으로 하회했습니다. 처음엔 코드 버그를 의심했지만, Wikidata API 응답 분석 결과 약 20%의 Q-ID에 영어/한국어 레이블이 아예 없다는 구조적 한계였습니다. 목표값 자체가 잘못 설정된 것이었습니다. **SLO는 코드뿐 아니라 외부 데이터 품질도 반영해야 한다는 걸 실감했습니다.**

---

### 결정 4 — Loki/Alloy 제거

**맥락**
로그 수집 스택(Loki + Alloy)이 174 MiB를 사용하면서도 실질적으로 활용하지 않았습니다. SLO 지표를 Loki에 저장하던 구조를 QuestDB로 이관하면 로그 스택 전체를 제거할 수 있었습니다.

**결과** (EC2 실측, benchmark/loki-removal/ 기준)

| 항목 | Before | After |
|---|---|---|
| 컨테이너 수 | 10개 | 8개 |
| CPU 합계 | 70.6% | **13.3%** |
| Swap | 700 MiB | **205 MiB** |
| 이미지 디스크 | — | 778MB 추가 절감 |

CPU가 57% 감소한 주원인은 Loki/Alloy 자체(1%)가 아니라, **이들이 유발하던 로그 스트림 처리 부하**(producer/redpanda/questdb)가 함께 사라진 연쇄 효과였습니다. 단순 컨테이너 제거가 아닌 데이터 흐름 전체의 변화였습니다.

---

## 기술적 도전과 해결

### 1. Grafana time series 패널 데이터 미표시

**증상**: `db has no time column: time column is missing` 에러. 수 시간 디버깅.

**가설 검증 과정**
1. QuestDB REST API 직접 테스트 → 정상 ✅
2. PG wire protocol(pg8000)으로 OID 확인 → timestamp OID 1114 정상 ✅
3. Grafana API (`POST /api/ds/query`)로 직접 테스트 → 에러 재현 ✅
4. `ts as time` alias 추가 테스트 → **해결**

**원인**: `grafana-postgresql-datasource` 플러그인이 컬럼 **타입(OID)**이 아닌 **이름**으로 time column을 식별했습니다. `ts`는 인식하지 못하고 `time`이라는 이름만 처리합니다. PG wire 레벨까지 파고들어서야 찾아낸 플러그인 내부 동작이었습니다.

**배운 점**: 추상화 레이어(Grafana 플러그인)가 어디에서 처리를 하는지 모를 때는 레이어를 한 단계씩 내려가며 직접 테스트하는 것이 가장 빠릅니다.

---

### 2. QuestDB 메모리 leak 의심 → mmap 동작 이해

**증상**: QuestDB RSS가 선형으로 계속 증가 (전환 직후 387MiB → 26시간 후 1,273MiB, +34MiB/h)

**오판**: 처음엔 메모리 누수로 의심했습니다.

**실제 원인**: QuestDB는 컬럼 파일을 mmap으로 매핑하며, OS page cache를 직접 활용합니다. 데이터가 쌓일수록 파일 크기가 증가하고 mmap'd pages가 RSS에 반영됩니다. OS는 메모리 압력이 생기면 cold pages를 자동 evict합니다.

**대응**: 누수가 아니므로 코드 수정이 아닌 운영 대응으로 해결했습니다.
- `mem_limit: 1100m` — cgroup 제약으로 OS eviction 유도
- TTL 5d — 데이터 볼륨 상한으로 mmap working set 간접 제한

이 과정에서 ClickHouse의 명시적 LRU 캐시 vs QuestDB의 OS page cache 위임 방식의 트레이드오프를 깊이 이해하게 됐습니다.

---

### 3. ElementTree `bool(element)` 함정

**증상**: Google News RSS 스크래핑에서 기사를 찾지 못하는 간헐적 버그

**원인**: Python의 `xml.etree.ElementTree`에서 `if not element` 조건이 element에 child가 없으면 `False`를 반환합니다. `<title>텍스트</title>` 같은 텍스트 노드만 있는 element도 falsy로 평가됩니다.

```python
# 잘못된 코드 (텍스트가 있어도 False)
if not title_el:
    continue

# 올바른 코드
if title_el is None:
    continue
```

**배운 점**: 표준 라이브러리도 직관과 다르게 동작하는 경우가 있습니다. "동작이 이상하다"고 느낄 때는 공식 문서의 주의 사항을 먼저 확인하는 습관을 갖게 됐습니다.

---

## 운영 경험에서 배운 것

### 숫자 없이는 아무것도 모른다

처음에 "Redpanda가 Kafka보다 가볍다"고 알고 있었지만, 실제로 p999 latency가 GC stress 상황에서 13ms vs 3.8ms라는 걸 측정하기 전까지는 그냥 문장에 불과했습니다. **직접 측정한 숫자만이 설득력 있습니다.**

### SLO의 목적은 알림이 아니라 판단 기준

SLO를 처음 설정할 때 "잘 동작하면 알림이 안 오겠지"라고 생각했습니다. 운영하다 보니 SLO의 진짜 가치는 **"이 정도면 충분한가?"를 판단하는 기준**이라는 걸 알게 됐습니다. D2 레이블 보강률 이슈처럼 목표값 자체를 재검토해야 하는 상황이 생겼을 때, SLO가 있었기에 그 논의를 시작할 수 있었습니다.

### 문서는 코드만큼 중요하다

40개 이상의 DEV_LOG 항목, 아키텍처 경량화 보고서, 벤치마크 원본 데이터를 모두 저장소에 함께 관리했습니다. 몇 주 후에 "왜 이렇게 했지?"라는 질문에 스스로 답할 수 있었고, 이 포트폴리오를 쓰는 것도 그 기록 덕분에 가능했습니다.

---

## 아직 해결하지 못한 것 (솔직하게)

- **D2 레이블 보강률 79~88%**: Wikidata 구조적 한계(~20% Q-ID에 레이블 없음)로 목표 80% 달성이 어렵습니다. 목표값 재조정 또는 레이블 보강 전략 개선이 필요합니다.
- **QuestDB cold read spike**: AWS EBS 환경에서 72h+ Grafana 뷰는 이론상 수십 초 지연이 가능합니다. 실사용 영향은 경미하지만 인지하고 운영 중입니다.
- **CI 테스트 단계 분리**: 현재 PR마다 276개 전체 테스트를 실행합니다. Smoke test(PR) / Full E2E(merge) 분리가 필요합니다.

---

## 기술 스택 요약

| 영역 | 기술 | 선택 이유 |
|---|---|---|
| 수집·보강 | Python 3.11, Pydantic | 타입 안전성, 스키마 검증 |
| 메시지 버스 | Redpanda | Kafka 호환 + 메모리 효율 (RSS -75%) |
| 시계열 DB | QuestDB 9.3.3 | warm 쿼리 7× 빠름, 메모리 효율 |
| 시각화 | Grafana + PostgreSQL wire | 표준 SQL, 플러그인 불필요 |
| AI 리포팅 | Claude Haiku (Anthropic) | 비용 효율적 LLM, 일일 트렌드 요약 |
| Datalake | Parquet(Snappy) + AWS S3 | 장기 보관, DuckDB 조회 가능 |
| 인프라 | Docker Compose, AWS EC2 t4g.small | IaC, 월 $15 운영비 |
| 테스트 | Pytest, pytest-mock | 276개 단위 테스트, CI 자동화 |

---

## 링크

- **GitHub**: https://github.com/puding-development/wikiStreams
- **아키텍처 경량화 상세 보고서**: [`docs/ARCH_LIGHTENING_REPORT.md`](ARCH_LIGHTENING_REPORT.md)
- **개발 기록 (DEV_LOG)**: [`docs/DEV_LOG.md`](DEV_LOG.md) — 40개 항목
- **SLO/SLI 문서**: [`docs/SLO.md`](SLO.md)
