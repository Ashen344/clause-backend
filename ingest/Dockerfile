

FROM python:3.11-slim
 
WORKDIR /app
 
# System deps needed by pymupdf
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmupdf-dev \
    && rm -rf /var/lib/apt/lists/*
 
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
 
COPY ingest.py extractor.py tasks.py upload.py ./

# Create non-root user and set ownership
RUN useradd -r -s /bin/false appuser && chown -R appuser /app

# Mount point for PDF files at runtime — ensure appuser can access it
VOLUME ["/data"]
RUN mkdir -p /data && chown appuser /data

USER appuser

ENTRYPOINT ["python", "ingest.py"]
CMD ["--help"]
 
