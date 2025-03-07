# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Install bash and necessary system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    bash \
    curl \
    git \
    jq \
    ca-certificates \
    gnupg \
    lsb-release \
    build-essential \
    python3-dev \
    libffi-dev \
    libyaml-dev && \
    curl -L "https://github.com/docker/compose/releases/download/v2.24.1/docker-compose-linux-x86_64" -o /usr/local/bin/docker-compose && \
    chmod +x /usr/local/bin/docker-compose && \
    apt-get clean \
    && rm -rf /var/lib/apt/lists/*  # Clean up apt cache to reduce image size

# Install Docker (using Docker's official script for installation)
RUN curl -fsSL https://get.docker.com | sh

# Add a default user to the image
RUN groupadd -g 1000 defaultgroup && \
    useradd -u 1000 -g defaultgroup -m defaultuser

# Allow UID and GID to be overridden at runtime
ARG UID=1000
ARG GID=1000
RUN groupmod -g ${GID} defaultgroup && \
    usermod -u ${UID} -g ${GID} defaultuser && \
    chown -R ${UID}:${GID} /home/defaultuser

# Copy the entire current directory into the container
COPY ./app/ /app/

# Set the working directory inside the container
WORKDIR /app

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt

# Switch to non-root user by default
USER defaultuser
