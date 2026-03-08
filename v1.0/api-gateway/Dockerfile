FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ shared/
COPY api-gateway/ api-gateway/

WORKDIR /app/api-gateway
CMD ["python", "gateway.py"]
