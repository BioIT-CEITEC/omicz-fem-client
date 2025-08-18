FROM python:3.10-slim

# Build-time arguments for user and group IDs
ARG UID=1000
ARG GID=1000

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        bash curl git jq ca-certificates gnupg lsb-release \
        build-essential python3-dev libffi-dev libyaml-dev sudo && \
    curl -L "https://github.com/docker/compose/releases/download/v2.24.1/docker-compose-linux-x86_64" -o /usr/local/bin/docker-compose && \
    chmod +x /usr/local/bin/docker-compose && \
    curl -fsSL https://get.docker.com | sh && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Create a user and group with the given UID and GID
RUN groupadd -g ${GID} prod || true && \
    useradd -m -u ${UID} -g prod -s /bin/bash prod

# Copy app and fix permissions
COPY ./app/ /app/
RUN chown -R ${UID}:${GID} /app

WORKDIR /app

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt

# Drop to non-root user
USER prod
