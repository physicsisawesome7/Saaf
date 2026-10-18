# syntax=docker/dockerfile:1.7
# Build from the repository root:
#   docker build -f packages/saaf-gateway/Dockerfile -t saaf-gateway .
FROM python:3.14-slim AS build
WORKDIR /src
RUN pip install --no-cache-dir build
COPY packages/saaf-core packages/saaf-core
COPY packages/saaf-gateway packages/saaf-gateway
COPY LICENSE NOTICE ./
RUN cp LICENSE NOTICE packages/saaf-core/ \
 && python -m build --wheel --outdir /wheels packages/saaf-core \
 && python -m build --wheel --outdir /wheels packages/saaf-gateway

FROM python:3.14-slim
RUN useradd --create-home --uid 10001 saaf
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels
USER saaf
ENV PYTHONUNBUFFERED=1
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/healthz')"
ENTRYPOINT ["saaf-gateway", "--host", "0.0.0.0", "--port", "8787"]
