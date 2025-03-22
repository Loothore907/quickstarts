#!/bin/bash
# health_check.sh - Monitor extraction process in Docker container

# Directory where to write status
SHARED_DIR="/home/computeruse/shared"

# Process name to monitor
PROCESS_NAME="python -m headless_browser.headless_extractor"

# Log file location
HEALTH_LOG="${SHARED_DIR}/health_check.log"

# Timeout in seconds
TIMEOUT=600

echo "Starting health check monitor" > $HEALTH_LOG
echo "Timeout set to $TIMEOUT seconds" >> $HEALTH_LOG
echo "Monitoring process: $PROCESS_NAME" >> $HEALTH_LOG

START_TIME=$(date +%s)

# Monitor loop
while true; do
    # Check if extraction process is running
    PROCESS_COUNT=$(ps aux | grep -v grep | grep "$PROCESS_NAME" | wc -l)
    CURRENT_TIME=$(date +%s)
    ELAPSED=$((CURRENT_TIME - START_TIME))
    
    echo "[$(date)] Process count: $PROCESS_COUNT, Elapsed: ${ELAPSED}s" >> $HEALTH_LOG
    
    # If process isn't running, exit health check
    if [ $PROCESS_COUNT -eq 0 ]; then
        echo "[$(date)] Extraction process not found, exiting health check" >> $HEALTH_LOG
        exit 0
    fi
    
    # Check for timeout
    if [ $ELAPSED -gt $TIMEOUT ]; then
        echo "[$(date)] TIMEOUT REACHED: $TIMEOUT seconds elapsed" >> $HEALTH_LOG
        echo "[$(date)] Forcefully terminating extraction process" >> $HEALTH_LOG
        
        # Add timeout alert to status file
        echo "I HAVE A PROBLEM: Extraction timed out after ${TIMEOUT} seconds (detected by health check)" > "${SHARED_DIR}/container_status.txt"
        
        # Kill the process
        pkill -f "$PROCESS_NAME"
        
        # Exit with error code
        exit 1
    fi
    
    # Sleep before next check
    sleep 5
done 