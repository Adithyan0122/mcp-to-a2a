FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ shared/
COPY notification-agent/ notification-agent/

WORKDIR /app/notification-agent
CMD ["python", "notification_agent.py"]
