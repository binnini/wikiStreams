# WikiStreams 트러블슈팅 기록

> 운영 중 마주친 문제와 해결 방법을 기록합니다.
> 아키텍처 의사결정 과정의 상세 배경은 [DEV_LOG.md](DEV_LOG.md)를 참조하세요.

---

## 1. Wikidata Q-ID 보강 아키텍처 결정

### 배경

분석 결과에 `Q24000605` 같은 Wikidata Q-ID가 다수 등장했지만, 실시간 파이프라인에서 매번 API를 호출하면 레이트 리밋과 처리 지연 문제가 있었습니다.

(실측: 30분간 약 1,000개의 고유 Q-ID 발생)

### 대안 비교

| 방안 | 장점 | 단점 | 결정 |
|---|---|---|---|
| A. PostgreSQL 캐시 | 인프라 재활용 | 네트워크 오버헤드, DB 부하 공유 | 차선 |
| B. Druid Lookups | 아키텍처 우수 | 대용량 덤프 파일 필수, 온디맨드 불가 | 기각 |
| **C. Producer-Side SQLite 캐시** | 단순, 빠름, 독립성, 영속성 | 다중 컨슈머 환경 부적합 | **채택** |

### 결론

단일 Producer 구조에서 SQLite 로컬 캐시가 가장 실용적입니다. 캐시 히트 시 API 호출 없이 즉시 응답, 미스 시 Wikidata API 50개 청크 일괄 조회 후 캐시 저장.

TTL 구조:
- 정상 엔티티 (레이블 있음): 30일
- 빈 레이블 엔티티 (레이블 없음): 3시간 ← 스테일 캐시 방지
- missing 엔티티: 3시간

---

## 2. QuestDB orphan 컨테이너 포트 충돌

### 증상

ClickHouse → QuestDB 전환 시 `questdb` 컨테이너가 네트워크에 연결되지 않고, Grafana에서 데이터소스 연결 실패.

### 원인

`clickhouse` 컨테이너가 포트 9000을 점유한 상태로 남아있어(`docker ps -a` 확인) QuestDB 기동 시 포트 충돌.

### 해결

```bash
docker compose down --remove-orphans
docker compose up -d
```

`--remove-orphans`로 compose 파일에서 제거된 orphan 컨테이너를 함께 정리.

---

## 3. SLI-A2 ClickHouse 성공률 항상 ~50% 고정

### 증상

Grafana SLO 대시보드에서 ClickHouse 쿼리 성공률이 항상 50%대로 표시됨. 실제 오류는 없는 상태.

### 원인

`system.query_log`에 모든 쿼리에 대해 `QueryStart`와 `QueryFinish` 두 개의 행이 기록됨. 분모에 `QueryStart`가 포함되어 분자(성공)/분모 비율이 ~50%로 고정됨.

### 해결

```sql
-- 변경 전
SELECT countIf(type = 'QueryFinish') / count() FROM system.query_log

-- 변경 후
SELECT countIf(type = 'QueryFinish') / count()
FROM system.query_log
WHERE type NOT IN ('QueryStart')
```

실제 수치: 99.92%

---

## 4. macOS에서 Promtail 로그 수집 불가

### 증상

Mac Mini(Apple Silicon)에서 Promtail이 `/var/lib/docker/containers` 마운트 실패. 컨테이너 로그 수집 안 됨.

### 원인

macOS Docker Desktop은 컨테이너를 내부 Linux VM에서 실행. 호스트에서 `/var/lib/docker/containers` 경로에 직접 접근 불가.

### 해결

Promtail → **Grafana Alloy** 교체. `loki.source.docker` 컴포넌트가 Docker socket API(`/var/run/docker.sock`)를 직접 사용하여 로그 수트리밍.

```hcl
# monitoring/alloy-config.alloy
loki.source.docker "containers" {
  host = "unix:///var/run/docker.sock"
  ...
}
```

---

## 5. Redpanda 서비스명 변경으로 인한 통합 테스트 실패

### 증상

```
FAILED tests/integration/test_producer_kafka_integration.py
```

### 원인

`docker-compose.yml`에서 `kafka-kraft` → `redpanda`로 서비스명이 변경되었으나, 통합 테스트의 fallback 경로에서 `port_for("kafka-kraft", 9092)`를 참조.

### 해결

```python
# 변경 전
port = docker_services.port_for("kafka-kraft", 9092)

# 변경 후
port = docker_services.port_for("redpanda", 9092)
```

---

## 6. S3 Exporter 초기 구현의 메모리 스파이크

### 증상

하루치 데이터(~100만 건)를 일괄 로드 시 메모리 사용량이 ~960 MB까지 급증.

### 원인

QuestDB `/exp` API에서 하루 전체 데이터를 한 번에 CSV로 다운로드 후 Arrow Table로 변환.

### 해결

시간별 24청크로 분할 처리 + `ParquetWriter` 순차 write로 변경.

```python
for hour in range(24):
    table = _fetch_hour_as_arrow(target, hour)  # 1시간치씩
    if writer is None:
        writer = pq.ParquetWriter(buf, table.schema, compression="snappy")
    writer.write_table(table)
    del table  # 즉시 메모리 해제
```

실측: 2.5시간치 기준 ~100 MB → ~50 MB (약 50% 절감).

---

## 7. QuestDB mmap RSS 선형 증가

### 증상

QuestDB 컨테이너 RSS가 24시간 관측 시 +34 MiB/h 선형 증가.

### 원인

QuestDB는 컬럼 파일을 mmap으로 읽어 OS page cache에 완전 위임. ClickHouse처럼 명시적 LRU 캐시 예산 설정이 없어, RAM이 넉넉한 환경에서는 RSS가 working set에 비례해 증가.

### 해결

두 가지 제어 수단 병행:
1. `mem_limit: 1100m` — cgroup 압력으로 강제 page eviction
2. `PARTITION BY DAY TTL 5d` — working set 상한 제한 (최대 5일치 컬럼 파일)

```yaml
# docker-compose.yml
questdb:
  mem_limit: 1100m
```

```sql
-- QuestDB 테이블 정의
wikimedia_events (...)
PARTITION BY DAY TTL 5d;
```
