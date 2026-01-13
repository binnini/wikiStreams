import os

# 보안 설정
SECRET_KEY = os.getenv("SUPERSET_SECRET_KEY", "superset_secret_key_12345")

# 데이터베이스 연동 (Superset 자체 메타데이터 저장을 위한 Postgres DB)
# Druid 연결 정보가 아닙니다. Superset 대시보드 정보를 저장할 곳입니다.
POSTGRES_USER = os.getenv("POSTGRES_USER", "druid")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "FoolishPassword")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB = "superset"  # Superset 전용 DB 사용 권장

SQLALCHEMY_DATABASE_URI = f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

# 언어 및 시간대 설정
BABEL_DEFAULT_LOCALE = "en"
# Druid는 UTC로 저장되지만 화면에서는 서울 시간으로 볼 수 있게 설정 가능
# DRUID_IS_KST = True

# 기타 기본 설정
ROW_LIMIT = 5000
FEATURE_FLAGS = {
    "DYNAMIC_PLUGINS": True,
}

# 로컬 환경 설정 (HTTP 접속 허용)
TALISMAN_ENABLED = False
