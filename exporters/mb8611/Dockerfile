FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY __init__.py hnap.py parser.py client.py exporter.py /app/exporters/mb8611/
RUN touch /app/exporters/__init__.py

EXPOSE 9611
CMD ["python", "-m", "exporters.mb8611.exporter"]
