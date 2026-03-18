#!/bin/bash

# Log file for setup
LOG_FILE="./app/receiver.log"
touch "$LOG_FILE"
chmod 666 "$LOG_FILE"

# Function to log messages
log_message() {
    echo "$(date +'%Y-%m-%d %H:%M:%S') $1" | tee -a "$LOG_FILE"
}

log_message "Starting setup_service.sh"

# Parse paths from config.py
CONFIG_FILE="./config/config.py"
DATA_PATH=$(grep -oP "data_path\s*=\s*'[^']+'" "$CONFIG_FILE" | awk -F"'" '{print $2}')
SANDBOX_PATH=$(grep -oP "sandbox_path\s*=\s*'[^']+'" "$CONFIG_FILE" | awk -F"'" '{print $2}')
HOST_FEMC_PATH=$(pwd)
UID=$(id -u)
GID=$(id -g)
USER_NAME=$(id -un)
DOCKER_GID=$(getent group docker | cut -d: -f3)

# Create .env file
cat > .env <<EOF
DATA_PATH=${DATA_PATH}
SANDBOX_PATH=${SANDBOX_PATH}
HOST_FEMC_PATH=${HOST_FEMC_PATH}
LOG_FILE=${LOG_FILE}
UID=${UID}
GID=${GID}
USER_NAME=${USER_NAME}
DOCKER_GID=${DOCKER_GID}
EOF

log_message "Resolved data_path: $DATA_PATH"
log_message "Resolved sandbox_path: $SANDBOX_PATH"
log_message "Log file path: $LOG_FILE"

# Run the docker compose command, redirecting stdout and stderr to receiver.log
echo "Checking for NVIDIA GPU availability on host..."

# Default to CPU
use_gpu=false
if command -v nvidia-smi &> /dev/null; then
    if gpu_output=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null); then
        gpu_count=$(echo "$gpu_output" | grep -c .)
        if [ "$gpu_count" -gt 0 ]; then
            echo "Detected $gpu_count GPU(s):"
            echo "$gpu_output"
            use_gpu=true
        fi
    fi
fi

# Launch the appropriate docker-compose config
if [ "$use_gpu" = true ]; then
    echo "Launching GPU-enabled containers..."
    docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d >> $LOG_FILE 2>&1
else
    echo "Launching CPU-only containers..."
    docker compose -f docker-compose.yml up -d >> $LOG_FILE 2>&1
fi

if [ $? -eq 0 ]; then
    log_message "Docker Compose successfully started."
    log_message "Receiver.py will run as host user inside container."
else
    log_message "Docker Compose encountered an error."
fi

log_message "Setup complete."