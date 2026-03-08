FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ shared/
COPY supplier-agent/ supplier-agent/

WORKDIR /app/supplier-agent
# ENV file is passed via docker-compose
CMD ["python", "supplier_agent.py"]
