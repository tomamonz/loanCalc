FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8710

RUN useradd -m appuser

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY . /app

RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8710

CMD ["python", "-m", "loan_calc_web.app"]
