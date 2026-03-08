FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ shared/
COPY finance-agent/ finance-agent/

WORKDIR /app/finance-agent
CMD ["python", "finance_agent.py"]
