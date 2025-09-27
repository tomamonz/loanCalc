# Używamy oficjalnego obrazu Pythona jako bazy
FROM python:3.12-slim

WORKDIR /app

# 1. Kopiowanie i instalacja zależności
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2. Kopiowanie kodu aplikacji
COPY . /app

# Konfiguracja serwera
ENV HOST 0.0.0.0
EXPOSE 8710
CMD ["python", "loan_calc_web/server.py"]
