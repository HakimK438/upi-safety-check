# Backend image. Build from the repository root:  docker build -f backend/Dockerfile -t upi-safety-api .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
# xgboost and lightgbm need the OpenMP runtime
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend
COPY backend/requirements.txt .
# No PyTorch: the neural network ships as NumPy arrays, which keeps the image small and the memory under 512 MB
RUN pip install --default-timeout=300 --retries 10 -r requirements.txt

# Only what the running app needs: code, trained models, the sample (and its prepared cache), the message data and the evaluation results
COPY backend/app app
COPY backend/models models
COPY backend/data/merchant_sample data/merchant_sample
COPY backend/data/spam.csv data/spam.csv
COPY docs/ml/fraud_results.json /app/docs/ml/fraud_results.json

EXPOSE 8010
# --proxy-headers so the rate limiter sees each visitor's address, not the platform's proxy
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8010} --proxy-headers --forwarded-allow-ips='*'"]
