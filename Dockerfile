FROM python:3.11-slim

# ติดตั้ง system dependencies สำหรับ PDF OCR
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-tha \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY tour_lookup_api.py .

# PORT ที่ Railway/Render จะ inject ผ่าน env var
ENV PORT=8000

EXPOSE 8000

CMD uvicorn tour_lookup_api:app --host 0.0.0.0 --port ${PORT}
