#!/bin/bash

# Create environment
source venv/bin/activate

# Read the SANDBOX_PATH variable from config/config.py
SANDBOX_PATH=$(python3 -c "import config.config as config; print(config.sandbox_path)")

# Check if the SANDBOX_PATH variable is set
if [[ -z "$SANDBOX_PATH" ]]; then
    echo "SANDBOX_PATH variable is not set in config/config.py."
    exit 1
fi

# Create the directory structure
mkdir -p "$SANDBOX_PATH"

# Change to the script's directory
cd "$(dirname "$0")" || exit 1

# Run the receiver script as a background process
nohup python3 receiver.py > receiver.log 2>&1 &



