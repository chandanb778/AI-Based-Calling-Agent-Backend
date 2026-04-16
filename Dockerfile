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
ENV PYTHONUNBUFFERED=1

COPY start.py start.py

CMD ["python", "start.py"]
