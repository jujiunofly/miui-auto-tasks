FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /srv/data /srv/logs

EXPOSE 8000

CMD ["python", "-m", "waitress", "--listen=0.0.0.0:8000", "--threads=2", "webapp.main:app"]
