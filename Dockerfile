FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/app/data MODEL_DIR=/app/models
WORKDIR /app
RUN groupadd --gid 10001 vision && useradd --uid 10001 --gid vision --no-create-home vision
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=vision:vision backend ./backend
COPY --chown=vision:vision frontend ./frontend
COPY --chown=vision:vision models ./models
RUN mkdir -p /app/data && chown vision:vision /app/data
USER vision
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health',timeout=3)"
CMD ["uvicorn","backend.app:app","--host","0.0.0.0","--port","8000","--workers","1","--ws-max-size","4194304","--timeout-graceful-shutdown","30"]
