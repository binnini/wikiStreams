FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . ./resource_monitor/
ENV PYTHONPATH=/app
CMD ["python", "-m", "resource_monitor.main"]
