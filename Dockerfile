FROM python:3.12-slim

WORKDIR /app

# Install gcc — needed to compile some Python packages (e.g. psycopg C extensions)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user.
# Running as root inside a container is a security risk — if the app is
# compromised, the attacker has root inside the container.
RUN useradd --create-home --shell /bin/bash appuser

# Copy dependency file first — before any app code.
# This is a Docker layer caching trick: if pyproject.toml doesn't change,
# Docker reuses the cached "pip install" layer and skips reinstalling everything.
COPY pyproject.toml .

# Install the project and all its dependencies
RUN pip install --no-cache-dir -e ".[dev]"

# Now copy the application code
COPY . .

# Switch to the non-root user for everything that follows
USER appuser

EXPOSE 8000

# Production command (docker-compose overrides this with --reload for dev)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
