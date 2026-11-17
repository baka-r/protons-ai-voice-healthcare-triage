FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 TZ=Asia/Karachi HF_HOME=/data/models
WORKDIR /app

COPY requirements.txt requirements-local-stt.txt ./
RUN pip install -r requirements.txt
# Optional free/offline STT last-resort fallback: build arg WITH_LOCAL_STT=1
ARG WITH_LOCAL_STT=0
RUN if [ "$WITH_LOCAL_STT" = "1" ]; then pip install -r requirements-local-stt.txt; fi

COPY pytest.ini ./
COPY app ./app
COPY knowledge ./knowledge
COPY seed ./seed
COPY tests ./tests

# run as an unprivileged user; /data is the only writable state
RUN useradd --system --uid 10001 --home-dir /app app && mkdir -p /data && chown -R app:app /data /app
USER app

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=4s --start-period=40s --retries=4 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).status==200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--ws-max-size", "2000000", "--no-server-header"]
