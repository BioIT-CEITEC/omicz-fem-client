#!/bin/bash

# Create environment
/usr/bin/python3 -m venv venv
python3 -m venv venv
source venv/bin/activate

# Install requirements
pip install -r requirements.txt

# Generate certificates
bash ./config/generate_certs.sh
sleep 15
chmod 700 ./config/rabbitmq-ca/

# Read the SANDBOX_PATH variable from config/config.py
SANDBOX_PATH=$(python3 -c "import config.config as config; print(config.sandbox_path)")

# Check if the SANDBOX_PATH variable is set
if [[ -z "$SANDBOX_PATH" ]]; then
    echo "SANDBOX_PATH variable is not set in config/config.py."
    exit 1
fi

# Create the directory structure
mkdir -p "$SANDBOX_PATH"/config  


