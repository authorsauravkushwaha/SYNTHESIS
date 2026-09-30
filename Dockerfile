# SYNTHESIS MVP — minimal, non-root, pinned container
FROM python:3.11-slim

RUN useradd --create-home --uid 10001 synthesis
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server ./server
COPY web ./web

USER synthesis
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]
