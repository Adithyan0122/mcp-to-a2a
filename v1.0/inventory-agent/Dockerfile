FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ shared/
COPY inventory-agent/ inventory-agent/

WORKDIR /app/inventory-agent
CMD ["python", "inventory_agent.py"]
