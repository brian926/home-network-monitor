FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY parser.py exporter.py /app/exporters/speedtest_bridge/
RUN touch /app/exporters/__init__.py /app/exporters/speedtest_bridge/__init__.py

EXPOSE 9798
CMD ["python", "-m", "exporters.speedtest_bridge.exporter"]
