#!/bin/bash

# Get the PID of the receiver process
PID=$(ps aux | grep 'receiver.py' | awk '{print $2}')

# Check if the process is running
if [ -z "$PID" ]; then
    echo "Receiver process is not running."
    exit 1
fi

# Kill the receiver process
kill $PID

echo "Receiver process stopped."
