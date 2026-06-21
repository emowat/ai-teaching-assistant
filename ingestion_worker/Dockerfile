FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY data_ingestion /app/data_ingestion
COPY rag /app/rag
COPY rag_eng /app/rag_eng

ENTRYPOINT ["python", "-m", "data_ingestion.ingestion_worker"]
