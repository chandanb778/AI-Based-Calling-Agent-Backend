FROM python:3.12-slim

WORKDIR /app

# System deps for audio processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ app/
COPY worker/ worker/
COPY scripts/ scripts/

# Port for FastAPI
EXPOSE 8081

# Run the combined FastAPI + LiveKit worker
CMD ["python", "-m", "app.main", "start"]
