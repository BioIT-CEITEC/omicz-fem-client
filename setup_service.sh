#!/bin/bash

# Setup paths

SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
CLIENT_PATH=$(dirname "$(realpath "$0")")
CLIENT_VENV="$CLIENT_PATH/venv"
CLIENT_EXEC="$CLIENT_PATH/receiver.py"
CLIENT_LOGS="$CLIENT_PATH/receiver.log"
SERVICE_NAME="flmanager_client"

############# Functions ###########

# Prompt user for service start on boot preference
prompt_service_start_on_boot() {
    read -p "Do you want the client (receiver) service to start on boot? (y/n): " start_on_boot
    case "$start_on_boot" in
        [Yy]*)
            enable_service=true
            ;;
        *)
            enable_service=false
            ;;
    esac
    echo ""
}

############# Checks ##############

# Check if systemd is installed

if ! command -v systemctl &> /dev/null; then
    echo "Error: systemd is not installed. Please install systemd before proceeding."
    exit 1
fi

# Check if the client (receiver) main executable exists
if [ ! -f "$CLIENT_EXEC" ]; then
    echo "Error: Python script $CLIENT_EXEC not found. Make sure the client main script is in the correct directory"
    exit 1
fi

# Check virtual environment

if [ ! -d "$CLIENT_VENV" ]; then
    echo "Error: Virtual environment not found at $CLIENT_VENV. Please set up the virtual environment before proceeding."
    exit 1
fi
if [ ! -f "$CLIENT_VENV/bin/python3" ]; then
    echo "Error: Virtual environment is not properly set up. Binary not found in $CLIENT_VENV/bin/python3."
    exit 1
fi
source $CLIENT_VENV/bin/activate
if [ $? -ne 0 ]; then
    echo "Error: Failed to activate the virtual environment."
    exit 1
fi
deactivate

############# Service Setup  ############

# Determine the WantedBy directive based on user preference

prompt_service_start_on_boot

if [ "$enable_service" = true ]; then
    wanted_by=default.target
else
    wanted_by=
fi

# Create systemd user directory
mkdir -p $SYSTEMD_USER_DIR

# Create the systemd service unit file
SERVICE_FILE=$SYSTEMD_USER_DIR/$SERVICE_NAME.service

cat <<EOL > $SERVICE_FILE
[Unit]
Description=FLmanager client (receiver) service
After=network.target

[Service]
Type=simple
ExecStart=$CLIENT_VENV/bin/python3 $CLIENT_EXEC
WorkingDirectory=$CLIENT_PATH
StandardOutput=file:$CLIENT_LOGS
StandardError=file:$CLIENT_LOGS
Restart=always
ExecStartPost=echo "The client is running. Logs are available at $CLIENT_LOGS"


[Install]
WantedBy=$wanted_by
EOL

echo "Service Unit $SERVICE_NAME.service created: $SERVICE_FILE"
echo ""

############# Service Start  ############

echo "Loading new unit..."
# Reload the systemd manager configuration
systemctl --user daemon-reload


# Enable the service to start on boot if chosen
if [ "$enable_service" = true ]; then
    echo "Enabling the service to start on boot."
    systemctl --user enable $SERVICE_NAME.service
else
    echo "Not enabling the service to start on boot. See below how to manually start it"
    systemctl --user disable $SERVICE_NAME.service
fi

# Start the service
echo ""
echo "Starting the service now..."
systemctl --user start  $SERVICE_NAME.service
sleep 1
systemctl --no-pager --user status $SERVICE_NAME.service

echo ""
echo "To manage the service:"
echo "- To stop the service:    systemctl --user stop    $SERVICE_NAME"
echo "- To start the service:   systemctl --user start   $SERVICE_NAME"
echo "- To restart the service: systemctl --user restart $SERVICE_NAME"
echo "- To check the status:    systemctl --user status  $SERVICE_NAME"
echo ""
echo "Check logs at $CLIENT_LOGS"
#echo "Logs can be viewed with: journalctl --user -u $SERVICE_NAME.service "
echo ""
