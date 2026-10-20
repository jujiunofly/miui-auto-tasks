FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /srv

COPY . .

RUN pip install --no-cache-dir -r requirements.txt && \
    python -m playwright install --with-deps chromium && \
    mkdir -p /srv/data /srv/logs

EXPOSE 8000

CMD ["python", "-m", "waitress", "--listen=0.0.0.0:8000", "webapp.main:app"]
