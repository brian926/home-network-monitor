FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends cron iputils-ping \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY grade.py render.py run.py /app/jobs/bufferbloat/
RUN touch /app/jobs/__init__.py /app/jobs/bufferbloat/__init__.py

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]
