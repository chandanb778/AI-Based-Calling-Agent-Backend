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

# Railway injects $PORT dynamically
EXPOSE 8081

# Railway edge proxy handles health checks automatically via railway.toml
# CMD is ignored if railway.toml startCommand is provided, but we set a safe default.
CMD ["sh", "-c", "python -m app.main start & uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8081}"]
