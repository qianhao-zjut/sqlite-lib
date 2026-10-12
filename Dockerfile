FROM python:3.12-slim

WORKDIR /app
COPY recordstore ./recordstore

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    RECORD_HOST=0.0.0.0 \
    RECORD_PORT=8787 \
    RECORD_DB=/data/records.db

EXPOSE 8787
CMD ["python", "-m", "recordstore"]
