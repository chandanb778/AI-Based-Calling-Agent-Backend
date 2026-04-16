import subprocess
import sys
import os
import signal

def main():
    port = os.environ.get("PORT", "8081")
    print(f"Starting services. Uvicorn on port {port}...", flush=True)

    # Start LiveKit Agent Worker
    worker_process = subprocess.Popen(
        [sys.executable, "-m", "app.main", "start"],
    )

    # Start Uvicorn FastAPI Server
    uvicorn_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", port],
    )

    def handle_sigterm(signum, frame):
        print("Received shutdown signal, terminating processes...", flush=True)
        worker_process.terminate()
        uvicorn_process.terminate()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    # Wait for either process to exit
    worker_process.wait()
    uvicorn_process.wait()

if __name__ == "__main__":
    main()
