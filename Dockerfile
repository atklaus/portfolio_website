# Use an official Python runtime as a parent image
FROM python:3.10-slim as base

# Setup env
ENV LANG C.UTF-8
ENV LC_ALL C.UTF-8
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONFAULTHANDLER 1
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

FROM base AS python-deps

# System deps for building wheels (only in build stage)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libgl1 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install Poetry + export plugin
RUN pip install --no-cache-dir "poetry==1.8.2" "poetry-plugin-export==1.7.1"

# Export and install dependencies into a virtualenv
WORKDIR /tmp
COPY pyproject.toml poetry.lock ./
RUN python -m venv /opt/venv && \
    . /opt/venv/bin/activate && \
    poetry export -f requirements.txt --output requirements.txt --without-hashes && \
    pip install --no-cache-dir -r requirements.txt

FROM base AS runtime

# Copy virtual env from python-deps stage
COPY --from=python-deps /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create a user and set work directory
RUN useradd --create-home appuser
WORKDIR /home/appuser
USER appuser

# Install application into container
COPY --chown=appuser . .

# Expose streamlit port
EXPOSE 8501

# Run the application
ENTRYPOINT ["streamlit", "run", "app.py"]
