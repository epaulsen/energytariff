#!/bin/bash

# Writes a random value to a text file every 15 seconds.
# The same file is read by the command_line sensor in configuration.yaml.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SENSOR_FILE="$SCRIPT_DIR/sensor-data.txt"

while true
do
    rand=$(( ( RANDOM % 9000 ) + 1000 ))
    echo $rand > "$SENSOR_FILE"
    sleep 15
done
