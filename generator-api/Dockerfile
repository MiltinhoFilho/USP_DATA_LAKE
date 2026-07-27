FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /workspace

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY ../src ./src
COPY . .