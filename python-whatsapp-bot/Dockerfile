# ── WhatsApp Bot ────────────────────────────────────────────
FROM python:3.11.7-slim

RUN apt-get update -qq && apt-get install -y --no-install-recommends \
      build-essential \
      && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# URLs for talking to Supplier-DB or any other micro-services
ENV SUPPLIER_API=http://supplier-db:8000

EXPOSE 7860
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
