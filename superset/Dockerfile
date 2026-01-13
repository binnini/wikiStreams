FROM apache/superset:latest

USER root

# 필요한 드라이버 설치
# root 권한으로 설치하여 모든 사용자가 접근 가능한 경로에 설치되도록 함
RUN pip install --no-cache-dir \
    psycopg2-binary \
    pydruid

# 설정 파일 및 초기화 스크립트 복사
# /app/pythonpath는 Superset이 설정을 로드하는 기본 경로 중 하나입니다.
COPY superset_config.py /app/pythonpath/superset_config.py
COPY init_superset.sh /app/init_superset.sh

RUN chmod +x /app/init_superset.sh

# 중요: root로 설치한 패키지 경로를 PYTHONPATH에 추가하여 가상환경에서도 인식되게 함
ENV PYTHONPATH="${PYTHONPATH}:/usr/local/lib/python3.10/site-packages"

USER superset
ENTRYPOINT [ "/app/init_superset.sh" ]