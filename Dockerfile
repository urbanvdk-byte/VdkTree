# VdkTree v0.4.1: force Python runtime on BotHost instead of Node.js autodetection.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/data \
    PORT=3000

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir -r /app/requirements.txt

COPY . /app
RUN mkdir -p /app/data

EXPOSE 3000

# app.py starts Uvicorn on 0.0.0.0 and reads PORT from the environment.
CMD ["python", "-u", "app.py"]
