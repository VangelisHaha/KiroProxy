# KiroProxy - Docker Image
# Optimized single-stage build

FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Create non-root user for security
RUN groupadd -r kiro && useradd -r -g kiro kiro

WORKDIR /app
RUN chown kiro:kiro /app

# Install dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY --chown=kiro:kiro . .

# Create directories with proper permissions
RUN mkdir -p logs && chown -R kiro:kiro logs

# Switch to non-root user
USER kiro

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; r = httpx.get('http://localhost:8080/v1/models', timeout=5); r.raise_for_status()" || exit 1

# Run the application
CMD ["python", "-m", "kiro_proxy.launcher"]
