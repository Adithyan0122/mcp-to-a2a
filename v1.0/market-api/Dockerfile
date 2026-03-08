FROM python:3.13-slim

WORKDIR /app

# Install shared dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared library
COPY shared/ shared/

# Copy agent code
COPY market-api/ market-api/

WORKDIR /app/market-api
CMD ["python", "market_api.py"]
