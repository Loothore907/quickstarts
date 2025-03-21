#!/bin/bash
set -e

# Check if we're running in headless mode
HEADLESS_MODE=${HEADLESS_MODE:-false}

# Always start the X server and virtual desktop
./start_all.sh

if [ "$HEADLESS_MODE" = "true" ]; then
    echo "Starting in headless mode..."
    
    # Check for required environment variables
    if [ -z "$EXTRACTION_URL" ]; then
        echo "ERROR: EXTRACTION_URL environment variable is required in headless mode"
        exit 1
    fi
    
    if [ -z "$EXTRACTION_INSTRUCTIONS" ]; then
        echo "ERROR: EXTRACTION_INSTRUCTIONS environment variable is required in headless mode"
        exit 1
    fi
    
    # Set default values for optional params
    EXTRACTION_OUTPUT=${EXTRACTION_OUTPUT:-"/home/computeruse/shared/extraction_result.json"}
    EXTRACTION_FORMAT=${EXTRACTION_FORMAT:-"json"}
    
    echo "Extraction URL: $EXTRACTION_URL"
    echo "Extraction Instructions: $EXTRACTION_INSTRUCTIONS"
    echo "Output Path: $EXTRACTION_OUTPUT"
    echo "Output Format: $EXTRACTION_FORMAT"
    
    # Start the NoVNC server for debug purposes
    ./novnc_startup.sh
    
    # Run headless extractor
    python -m computer_use_demo.headless_extractor \
        --url "$EXTRACTION_URL" \
        --instructions "$EXTRACTION_INSTRUCTIONS" \
        --output "$EXTRACTION_OUTPUT" \
        --format "$EXTRACTION_FORMAT" \
        --provider "${API_PROVIDER:-anthropic}" \
        --model "${MODEL:-claude-3-7-sonnet-20250219}" \
        --tool-version "${TOOL_VERSION:-computer_use_20250124}"
    
    # Exit code from the script becomes the container's exit code
    exit $?
else
    # Original interactive mode
    echo "Starting in interactive mode..."
    
    # Start the NoVNC server
    ./novnc_startup.sh

    # Start the HTTP server for the combined interface
    python http_server.py > /tmp/server_logs.txt 2>&1 &

    # Start Streamlit
    STREAMLIT_SERVER_PORT=8501 python -m streamlit run computer_use_demo/streamlit.py > /tmp/streamlit_stdout.log &

    echo "✨ Computer Use Demo is ready!"
    echo "➡️  Open http://localhost:8080 in your browser to begin"

    # Keep the container running
    tail -f /dev/null
fi