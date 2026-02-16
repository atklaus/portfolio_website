# Use an official Python runtime as a parent image
FROM python:3.10-slim-bookworm as base

# Setup env
ENV LANG C.UTF-8
ENV LC_ALL C.UTF-8
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONFAULTHANDLER 1
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV POETRY_NO_INTERACTION=1
ENV POETRY_VIRTUALENVS_CREATE=false

FROM base AS builder

# System deps for building wheels (only in build stage)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libgl1 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN pip install --no-cache-dir "poetry==2.0.1"

WORKDIR /app
COPY pyproject.toml poetry.lock ./
RUN poetry install --only main --no-root

FROM base AS runtime

# Runtime libs only
RUN apt-get update && \
    apt-get install -y --no-install-recommends libgl1 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy installed deps
COPY --from=builder /usr/local /usr/local

# Create a user and set work directory
RUN useradd --create-home appuser
WORKDIR /home/appuser
USER appuser

# Install application into container
COPY --chown=appuser . .

# Expose streamlit port
EXPOSE 8501

# Run the application
ENTRYPOINT ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
