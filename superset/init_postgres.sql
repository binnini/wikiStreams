-- Superset 메타데이터를 위한 별도 데이터베이스 생성
SELECT 'CREATE DATABASE superset'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'superset')\gexec
