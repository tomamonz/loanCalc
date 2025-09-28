# Base
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Create non-root user
RUN useradd -m appuser

WORKDIR /app

# System deps (only if your requirements need them; otherwise you can skip)
# RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
#     && rm -rf /var/lib/apt/lists/*

# 1) Copy and install dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2) Copy app
COPY . /app

# Fix permissions for mounted logs etc.
RUN chown -R appuser:appuser /app
USER appuser

# Runtime config
ENV HOST=0.0.0.0
EXPOSE 8710

# Consider a proper WSGI/ASGI server for production (gunicorn/uvicorn)
CMD ["python", "loan_calc_web/server.py"]
