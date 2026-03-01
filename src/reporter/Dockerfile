FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . ./reporter/
ENV PYTHONPATH=/app
CMD ["python", "-m", "reporter.main"]
