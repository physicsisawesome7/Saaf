# Build from the monorepo root so Saaf (the PII layer) installs from source:
#   docker build -f packages/smriti/Dockerfile -t safearly/smriti .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SMRITI_DATA_DIR=/data
WORKDIR /app

COPY packages/saaf-core /src/saaf-core
COPY packages/smriti /src/smriti
RUN pip install --no-cache-dir /src/saaf-core "/src/smriti[tables,qdrant,postgres,s3]" \
 && useradd --system --uid 10001 smriti && mkdir -p /data && chown smriti /data

USER smriti
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["smriti", "serve", "--host", "0.0.0.0", "--port", "8000", "--seed"]
