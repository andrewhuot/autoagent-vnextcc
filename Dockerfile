# Stage 1: Build frontend
FROM node:20-alpine AS frontend-build

WORKDIR /app/web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# Stage 2: Python application
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy Python project files
COPY pyproject.toml ./
COPY runner.py ./
COPY agent/ ./agent/
COPY api/ ./api/
COPY configs/ ./configs/
COPY deployer/ ./deployer/
COPY evals/ ./evals/
COPY logger/ ./logger/
COPY observer/ ./observer/
COPY optimizer/ ./optimizer/

# Install Python dependencies
RUN pip install --no-cache-dir -e ".[dev]" 2>/dev/null || pip install --no-cache-dir -e .

# Copy built frontend
COPY --from=frontend-build /app/web/dist ./web/dist

# Create data directory
RUN mkdir -p /app/data

# Environment
ENV AUTOAGENT_DB=/app/data/conversations.db
ENV AUTOAGENT_CONFIGS=/app/data/configs
ENV AUTOAGENT_MEMORY_DB=/app/data/optimizer_memory.db
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

ENTRYPOINT ["python", "runner.py"]
CMD ["server", "--host", "0.0.0.0", "--port", "8000"]
