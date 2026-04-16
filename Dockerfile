FROM python:3.12-slim

WORKDIR /app

# System deps for audio processing + onnxruntime (Silero VAD)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ app/
COPY worker/ worker/
COPY scripts/ scripts/

# Railway injects $PORT dynamically — expose a default for local use
EXPOSE 8081

# Health check so Railway knows the container is alive
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:' + __import__('os').environ.get('PORT','8081') + '/health')"

# Entrypoint: start both FastAPI and the LiveKit worker
# 'start' subcommand is needed for the LiveKit CLI (Typer) to actually run the worker
CMD ["python", "-m", "app.main", "start"]
