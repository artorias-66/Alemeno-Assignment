#!/bin/bash
# Start Celery worker in the background
celery -A celery_app.celery worker --loglevel=info &

# Start FastAPI server in the foreground
# Render automatically injects the PORT environment variable (usually 10000)
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
