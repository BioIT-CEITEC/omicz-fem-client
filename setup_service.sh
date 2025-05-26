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

# Create .env file with DATA_PATH and SANDBOX_PATH
echo "DATA_PATH=${DATA_PATH}" > .env
echo "SANDBOX_PATH=${SANDBOX_PATH}" >> .env
echo "HOST_FEMC_PATH=${HOST_FEMC_PATH}" >> .env
echo "LOG_FILE=${LOG_FILE}" >> .env

# Log a message indicating setup
echo "Resolved data_path: $DATA_PATH"
echo "Resolved sandbox_path: $SANDBOX_PATH"
echo "Log file path: $LOG_FILE"

# Run the docker compose command, redirecting stdout and stderr to receiver.log
echo "Checking for NVIDIA GPU availability on host..."

# Default to CPU
use_gpu=false

# Check if `nvidia-smi` is installed
if ! command -v nvidia-smi &> /dev/null; then
    echo "nvidia-smi not found. Assuming no GPU available."
else
    # Try running it and catching any errors
    if gpu_output=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null); then
        gpu_count=$(echo "$gpu_output" | grep -c .)
        if [ "$gpu_count" -gt 0 ]; then
            echo "Detected $gpu_count GPU(s):"
            echo "$gpu_output"
            use_gpu=true
        else
            echo "nvidia-smi ran but found no GPUs."
        fi
    else
        echo "nvidia-smi found but failed to run correctly. Falling back to CPU."
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

# Check if Docker Compose command was successful
if [ $? -eq 0 ]; then
    echo "Docker Compose successfully started." >> $LOG_FILE
else
    echo "Docker Compose encountered an error." >> $LOG_FILE
fi

echo "Setup complete."
