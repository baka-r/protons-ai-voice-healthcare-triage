FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 TZ=Asia/Karachi
WORKDIR /app
RUN pip install "fastapi>=0.115" "uvicorn>=0.30" "pydantic>=2" tzdata
COPY app.py patients.json ./
RUN useradd --system --uid 10002 app && chown -R app:app /app
USER app
EXPOSE 9000
HEALTHCHECK --interval=15s --timeout=3s --retries=3 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:9000/health', timeout=2).status==200 else 1)"
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "9000", "--no-server-header"]
