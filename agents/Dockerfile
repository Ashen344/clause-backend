FROM python:3.11-slim

WORKDIR /app

# System deps — retry on mirror failures
RUN for i in 1 2 3; do \
      apt-get update --fix-missing && \
      apt-get install -y --no-install-recommends --fix-missing curl && \
      break || sleep 10; \
    done && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps first (layer cached unless requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir --timeout 300 --retries 5 -r requirements.txt

# Copy application code
COPY main.py tools.py ./
COPY agents/ ./agents/
COPY templates/ ./templates/

# Gemini model configuration
ENV GEMINI_MODEL=gemini-2.0-flash
ENV GEMINI_RPM=15
ENV GEMINI_RPD=500

# Create non-root user and set ownership
RUN useradd -r -s /bin/false appuser && chown -R appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
