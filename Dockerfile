FROM python:3.12-slim

WORKDIR /app

# Dependências de sistema para pdfplumber
RUN apt-get update && apt-get install -y \
    libpoppler-cpp-dev \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY static/ static/

# Pasta de dados persistente
RUN mkdir -p /app/data

EXPOSE 5000

CMD ["python", "app.py"]
