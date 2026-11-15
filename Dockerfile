FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./
COPY static ./static
COPY data ./data

ENV PYTHONUNBUFFERED=1
# Cloud Run は $PORT で待ち受ける（app.py が読む）
EXPOSE 8080

CMD ["python", "app.py"]
