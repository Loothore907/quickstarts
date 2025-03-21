#!/bin/bash

# Ensure API key is set
if [ -z "$ANTHROPIC_API_KEY" ]; then
  if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
  fi
  
  if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "Error: ANTHROPIC_API_KEY is not set"
    echo "Please set it in your environment or create a .env file with ANTHROPIC_API_KEY=<your_key>"
    exit 1
  fi
fi

# Check required parameters
if [ -z "$1" ] || [ -z "$2" ]; then
  echo "Usage: $0 <url> <instructions> [output_file] [format]"
  echo ""
  echo "Arguments:"
  echo "  url             - URL to extract data from"
  echo "  instructions    - Instructions for Claude on what data to extract"
  echo "  output_file     - Output file path (default: extraction_results.json)"
  echo "  format          - Output format: json, csv, or txt (default: json)"
  echo ""
  echo "Environment variables:"
  echo "  ANTHROPIC_API_KEY      - Your Anthropic API key"
  echo "  API_PROVIDER           - API provider: anthropic, bedrock, or vertex (default: anthropic)"
  echo "  MODEL                  - Model to use (default: claude-3-7-sonnet-20250219)"
  echo "  TOOL_VERSION           - Tool version (default: computer_use_20250124)"
  echo ""
  echo "Example:"
  echo "  $0 \"https://example.com\" \"Extract all product names and prices\" \"products.json\" \"json\""
  exit 1
fi

URL="$1"
INSTRUCTIONS="$2"
OUTPUT_FILE="${3:-extraction_results.json}"
FORMAT="${4:-json}"

# Create shared directory if it doesn't exist
mkdir -p shared

# Run docker container in headless mode
echo "Starting headless extraction..."
echo "URL: $URL"
echo "Instructions: $INSTRUCTIONS"
echo "Output file: $OUTPUT_FILE"
echo "Format: $FORMAT"

# Run the container
docker run --rm \
  -e HEADLESS_MODE=true \
  -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  -e API_PROVIDER="${API_PROVIDER:-anthropic}" \
  -e MODEL="${MODEL:-claude-3-7-sonnet-20250219}" \
  -e TOOL_VERSION="${TOOL_VERSION:-computer_use_20250124}" \
  -e EXTRACTION_URL="$URL" \
  -e EXTRACTION_INSTRUCTIONS="$INSTRUCTIONS" \
  -e EXTRACTION_OUTPUT="/home/computeruse/shared/$OUTPUT_FILE" \
  -e EXTRACTION_FORMAT="$FORMAT" \
  -v "$HOME/.anthropic:/home/computeruse/.anthropic" \
  -v "$(pwd)/shared:/home/computeruse/shared" \
  -p 6080:6080 \
  ghcr.io/anthropics/anthropic-quickstarts:computer-use-demo-latest

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
  echo ""
  echo "Extraction completed successfully!"
  echo "Results saved to: $(pwd)/shared/$OUTPUT_FILE"
  
  # Also check for metadata file
  METADATA_FILE="${OUTPUT_FILE%.*}.metadata.json"
  if [ -f "shared/$METADATA_FILE" ]; then
    echo "Metadata saved to: $(pwd)/shared/$METADATA_FILE"
  fi
else
  echo ""
  echo "Extraction failed with exit code: $EXIT_CODE"
  echo "Check the logs for more information."
fi

exit $EXIT_CODE