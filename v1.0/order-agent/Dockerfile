FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ shared/
COPY order-agent/ order-agent/

WORKDIR /app/order-agent
CMD ["python", "order_agent.py"]
