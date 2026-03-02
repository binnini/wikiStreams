# Data Engineering Lifecycle — Evaluation Kits

평가 목적으로 재구성. 각 항목은 **핵심 질문 → 평가 기준 → 주요 리스크** 순으로 정리.

---

## 1. Data Source System

| # | 핵심 질문 | 평가 기준 | 주요 리스크 |
|---|-----------|-----------|-------------|
| 1 | **원천의 본질**: 앱인가? IoT인가? | 정형 배치 vs 무한 스트리밍 여부 결정 | 아키텍처 선택 오류 |
| 2 | **데이터 보존 기간** | 삭제/덮어쓰기 주기 → 파이프라인 SLA 결정 | 수집 실패 시 유실 |
| 3 | **생성 속도** (events/s, GB/h) | 인프라 용량 산정 기준 | 과소 프로비저닝 |
| 4 | **데이터 일관성** | null·타입 오류 빈도 → 정제 로직 복잡도 | Garbage In/Out |
| 5 | **에러 발생 빈도** | 재시도 로직(Exponential Backoff) 필요성 판단 | 파이프라인 단절 |
| 6 | **중복 데이터 가능성** | 멱등성(Idempotency) 설계 필요 여부 | 집계 오염 |
| 7 | **Late-arriving / Out-of-order 데이터** | 스트리밍: Watermark / 배치: 파티션 재처리 필요 | 집계 누락·오류 |
| 8 | **스키마 복잡도** | 멀티 조인 필요 시 ELT 방식 선호 | 원천 DB 부하 |
| 9 | **스키마 변경 대응** | Schema Registry 또는 Data Contract 존재 여부 | 파이프라인 중단 |
| 10 | **수집 주기** | 실시간 / 마이크로배치 / 일별 배치 결정 요소 | 비용·지연 불균형 |
| 11 | **Stateful 원천**: 스냅숏 vs CDC | 스냅숏: 간단하지만 부하↑ / CDC(Debezium): 효율적이나 복잡 | 원천 DB 과부하 |
| 12 | **데이터 제공자** | 내부/외부 여부 → Rate Limit, SLA, 장애 연락망 | 의존성 장애 전파 |
| 13 | **원천 조회의 성능 영향** | Read Replica 또는 야간 배치 필요 여부 | 운영 서비스 다운 |
| 14 | **업스트림 의존 관계** | Stale data 위험 / Airflow DAG 스케줄 설계 기준 | 조용한 데이터 오류 |
| 15 | **데이터 품질 검사** | Anomaly 감지 알림 체계 존재 여부 | 비즈니스 팀이 먼저 발견 |

---

## 2. Storage System

| # | 핵심 질문 | 평가 기준 |
|---|-----------|-----------|
| 1 | **읽기·쓰기 속도 적합성** | OLTP vs OLAP 워크로드 매칭 여부 |
| 2 | **파이프라인 병목 가능성** | 스토리지 I/O가 다운스트림 처리속도를 제한하지 않는지 |
| 3 | **스토리지 작동 방식 이해** | Anti-pattern 사용 여부 (예: 객체 스토리지에 임의 수정) |
| 4 | **확장성 (Scalability)** | 수평 확장(Scale-out), IOPS 제한 고려 여부 |
| 5 | **SLA 충족 여부** | 가용성, 응답 지연이 소비자 요구를 만족하는지 |
| 6 | **메타데이터 수집** | Data Lineage, 스키마 변경 이력 추적 여부 |
| 7 | **순수 스토리지 vs 웨어하우스** | 객체 스토리지(Data Lake) / DW(Snowflake·BigQuery·ClickHouse) 구분 |
| 8 | **스키마 정책** | Schema-on-read(유연) vs Schema-on-write(엄격) 선택 |
| 9 | **데이터 거버넌스** | Golden Record, 마스터 데이터 관리 방식 |
| 10 | **법령·데이터 주권** | GDPR 등 지역별 데이터 격리, 암호화 여부 |

---

## 3. Data Ingestion System

| # | 핵심 질문 | 평가 기준 |
|---|-----------|-----------|
| 1 | **재사용 가능성** | Single Source of Truth → 다운스트림 공유 구조인지 |
| 2 | **내결함성 (Fault Tolerance)** | 멱등성 설계, 복구 후 누락 없이 재수집 가능한지 |
| 3 | **목적지 (Destination)** | 객체 스토리지 / DW / 메시지 큐 중 어디로 가는지 |
| 4 | **접근 빈도** | Hot(인메모리 캐시) vs Cold(아카이브) 경로 분리 여부 |
| 5 | **도착 데이터 용량** | 트래픽 스파이크 대비 버퍼·오토스케일링 설계 여부 |
| 6 | **데이터 포맷** | JSON/CSV/Avro/Protobuf → 직렬화·스키마 레지스트리 필요성 |
| 7 | **즉시 사용 가능 여부** | ETL(수집 전 변환) vs ELT(수집 후 변환) 선택 기준 |
| 8 | **스트리밍 인플라이트 변환** | Flink·Spark Streaming 필요 여부 |

### 스트리밍 vs 배치 판단 기준

| 질문 | 고려 사항 |
|------|-----------|
| 실시간 수집의 구체적 이점은? | 배치 대비 개선되는 비즈니스 지표 |
| 스트리밍 비용·복잡도 감수 가치? | 인프라 비용 + 유지보수 난이도 vs 실시간 가치 |
| 장애 시 Exactly-once 보장? | 체크포인트, Failover 설계 |
| 관리형(Kinesis·Pub/Sub) vs 자체 운영(Kafka·Flink)? | 팀 역량, 예산, 운영 부담 |
| 운영 DB에서 수집 시 성능 영향? | CDC(Debezium) 도입 여부 |

---

## 4. Data Transformation System

| # | 핵심 질문 | 평가 기준 |
|---|-----------|-----------|
| 1 | **비용 vs ROI** | 변환 연산 비용 < 비즈니스 가치인가? |
| 2 | **단순성·독립성** | 단일 책임 원칙, 모듈화 여부 |
| 3 | **비즈니스 규칙 반영** | 코드가 실제 비즈니스 로직을 정확히 구현하는가? |

---

## 5. Undercurrents (횡단 관심사)

### 5-1. Security

**핵심 원칙:** 공동 책임 모델 이해 + Zero Trust 설계

- [ ] **최소 권한 원칙** 적용
- [ ] 필요 기간에만 데이터 접근 허용 (임시 자격증명 등)
- [ ] Encryption(전송 중·저장 중), Tokenization, Masking, Obfuscation 적용
- [ ] IAM role·policy·group, 네트워크 보안, 비밀번호 정책 반영

---

### 5-2. Data Management

**핵심 원칙:** 데이터 수명 주기 전체를 관장하는 End-to-End 시각

| 항목 | 체크 포인트 |
|------|-------------|
| **Data Governance** | Discoverability(찾기) + Accountability(신뢰) 기반 구축 |
| **Metadata 수집** | Business / Technical / Operational / Reference 4종 관리 |
| **Data Accountability** | 테이블·필드 단위 Owner 지정, 장애 시 R&R 명확화 |
| **Data Quality** | Accuracy(정확성) · Completeness(완전성) · Timeliness(적시성) |
| **Data Modeling** | 소비자 Use Case에 맞는 모델 (Star Schema, Data Vault 등) |
| **Data Lineage** | Audit Trail 기록 → DODD 기반 디버깅 |
| **Data Integration** | 범용 API·개방 포맷 → 벤더 Lock-in 회피 |
| **Data Lifecycle Management** | 스토리지 계층 이동·삭제 정책 및 메타데이터 연동 |
| **Ethics & Privacy** | PII 마스킹, 개인정보 처리 방침 준수 |

> **거버넌스 실패 사례:** 분석가가 수십 개 테이블을 뒤적이며 데이터 타당성을 확신할 수 없는 상태 → 조직 전체의 데이터 신뢰도 붕괴

---

### 5-3. DataOps

**목표:** Cycle Time 단축 + 높은 데이터 품질 + 투명한 모니터링

- [ ] **Automation**: Cron / Airflow / Dagster 등 조직 성숙도에 맞는 Orchestration
  - Version control, CI/CD, 데이터 품질·Drift·메타데이터 무결성 검사 포함
- [ ] **Observability**: "무엇이" 아닌 "왜 고장 났는가" 파악 가능한 수준
  - 데이터 볼륨 변화, 스키마 변경, Data Drift 사전 감지
- [ ] **Incident Response**: MTTD(인지 시간) · MTTR(해결 시간) 최소화
  - 이해관계자보다 엔지니어가 먼저 감지 → 선제적 알림 + 사후 회고 체계

---

### 5-4. Data Architecture

**핵심 원칙:** 유행 아닌 **조직 규모·스킬셋에 맞는 Trade-off 최적화**

- 비용과 운영 간소화 균형 추구
- 컴포넌트 교체 가능한 **모듈형 설계** 지향
- Source → Ingestion → Store → Transform → Serving 전 구간 설계 일관성

---

### 5-5. Orchestration

**체크 포인트:**
- 오케스트레이터 자체가 **고가용성**으로 운영되는가?
- 단순 스케줄링을 넘어 **데이터 의존성 관리, Retry, SLA 모니터링** 수행하는가?
- 장애 시 파이프라인 전체가 멈추지 않는 Failover 구조인가?

---

### 5-6. Software Engineering

**체크 포인트:**

| 항목 | 기준 |
|------|------|
| **테스트 커버리지** | Unit / Integration / E2E / Smoke 적절히 혼용 |
| **오픈소스 활용** | TCO·기회비용 대비 자체 구현 vs OSS 선택 근거 |
| **IaC** | Terraform 등으로 인프라 코드화 → 재현성·버전 관리·DR 확보 |
