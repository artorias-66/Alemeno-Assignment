#!/bin/bash
# Start Celery worker in the background
# We use --pool=solo to strictly limit memory usage to a single process so we don't exceed Render's 512MB free tier limit
celery -A celery_app.celery worker --loglevel=info --pool=solo &

# Start FastAPI server in the foreground
# Render automatically injects the PORT environment variable (usually 10000)
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
