FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ shared/
COPY celery-worker/ celery-worker/

WORKDIR /app/celery-worker
CMD ["celery", "-A", "celery_app:celery_app", "worker", "--loglevel=info", "--concurrency=4"]
