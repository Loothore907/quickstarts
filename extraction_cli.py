#!/usr/bin/env python3
"""
Enhanced CLI tool for triggering headless web extractions with improved feedback.
"""

import argparse
import os
import subprocess
import sys
import json
import time
import re
import threading
import signal
from datetime import datetime
from pathlib import Path
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("extraction.log")],
)
logger = logging.getLogger("extraction-cli")

# Default values
DEFAULT_OUTPUT_DIR = Path("./shared")
DEFAULT_FORMAT = "json"
DEFAULT_MODEL = "claude-3-7-sonnet-20250219"
API_PROVIDER = "anthropic"
STATUS_UPDATE_INTERVAL = 3  # seconds

class ExtractionMonitor:
    """Monitors extraction process and provides status updates."""
    
    def __init__(self, shared_dir, output_file):
        self.shared_dir = shared_dir
        self.output_file = output_file
        self.status_file = shared_dir / "extraction_status.txt"
        self.running = False
        self.start_time = None
        self.process = None
        
    def start(self, process):
        """Start monitoring the extraction process."""
        self.process = process
        self.start_time = time.time()
        self.running = True
        
        # Create initial status file
        self._write_status("Starting extraction process...")
        
        # Start monitoring thread
        self.monitor_thread = threading.Thread(target=self._monitor_loop)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        
    def stop(self):
        """Stop monitoring the extraction process."""
        self.running = False
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=1.0)
    
    def _monitor_loop(self):
        """Main monitoring loop."""
        dots = 0
        spinner = ["|", "/", "-", "\\"]
        spinner_idx = 0
        
        while self.running:
            if self.process.poll() is not None:
                # Process completed
                self._write_status("Extraction completed")
                self.running = False
                break
                
            # Check for status file in Docker container's shared directory
            container_status_file = self.shared_dir / "container_status.txt"
            if container_status_file.exists():
                status = container_status_file.read_text(errors='replace')
                self._write_status(status)
            else:
                # No status file from container, show general status
                elapsed = time.time() - self.start_time
                spinner_char = spinner[spinner_idx]
                spinner_idx = (spinner_idx + 1) % len(spinner)
                
                status = f"{spinner_char} Extraction in progress ({elapsed:.0f}s elapsed)"
                dots = (dots + 1) % 4
                self._write_status(status + "." * dots)
            
            time.sleep(STATUS_UPDATE_INTERVAL)
    
    def _write_status(self, status):
        """Write status to status file and terminal."""
        if self.status_file.parent.exists():
            try:
                with open(self.status_file, 'w', encoding='utf-8') as f:
                    f.write(status)
            except Exception as e:
                logger.error(f"Error writing status file: {e}")
        
        # Also print to console with carriage return to update in place
        elapsed = time.time() - self.start_time if self.start_time else 0
        sys.stdout.write(f"\r[{elapsed:.0f}s] {status}".ljust(80))
        sys.stdout.flush()
    
    def get_elapsed_time(self):
        """Get elapsed time in seconds."""
        if not self.start_time:
            return 0
        return time.time() - self.start_time

def get_input(prompt, default=None, required=True):
    """Get input from user with optional default value."""
    default_display = f" [{default}]" if default else ""
    while True:
        value = input(f"{prompt}{default_display}: ").strip()
        if not value and default:
            return default
        if not value and required:
            print("This field is required.")
            continue
        return value

def get_multiline_input(prompt):
    """Get multiline input from user."""
    print(f"{prompt} (Enter a blank line to finish):")
    lines = []
    while True:
        line = input()
        if not line:
            break
        lines.append(line)
    return "\n".join(lines)

def normalize_url(url):
    """Normalize URL by adding https:// if missing."""
    if not url.startswith('http'):
        url = 'https://' + url
    return url

def create_docker_command(url, instructions, output_file, output_format, api_key=None):
    """Create Docker command for extraction."""
    # Normalize URL
    url = normalize_url(url)
    
    # Ensure output directory exists
    DEFAULT_OUTPUT_DIR.mkdir(exist_ok=True)
    
    # Prepare Docker command
    cmd = [
        "docker", "run", "--rm",
        "-e", "HEADLESS_MODE=true",
        "-e", f"EXTRACTION_URL={url}",
        "-e", f"EXTRACTION_INSTRUCTIONS={instructions}",
        "-e", f"EXTRACTION_OUTPUT=/home/computeruse/shared/{output_file}",
        "-e", f"EXTRACTION_FORMAT={output_format}",
        "-e", f"API_PROVIDER={API_PROVIDER}",
        "-e", f"MODEL={DEFAULT_MODEL}",
    ]
    
    # Add API key if provided
    if api_key:
        cmd.extend(["-e", f"ANTHROPIC_API_KEY={api_key}"])
    else:
        # Try to get from environment
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if api_key:
            cmd.extend(["-e", f"ANTHROPIC_API_KEY={api_key}"])
    
    # Add volume mounts - use Windows path syntax
    import os
    home_dir = os.path.expanduser("~")
    current_dir = os.getcwd()
    
    cmd.extend([
        "-v", f"{current_dir}\\shared:/home/computeruse/shared",
        "-v", f"{home_dir}\\.anthropic:/home/computeruse/.anthropic",
    ])
    
    # Add image name
    cmd.append("ghcr.io/anthropics/anthropic-quickstarts:computer-use-demo-latest")
    
    return cmd

def run_extraction(url, instructions, output_file, output_format, api_key=None):
    """Run the headless extraction using Docker."""
    # Prepare command
    cmd = create_docker_command(url, instructions, output_file, output_format, api_key)
    
    # Log the command (mask API key)
    log_cmd = list(cmd)
    for i, item in enumerate(log_cmd):
        if isinstance(item, str) and item.startswith("ANTHROPIC_API_KEY="):
            log_cmd[i] = "ANTHROPIC_API_KEY=************"
    logger.info(f"Running command: {' '.join(log_cmd)}")
    
    # Create monitor
    monitor = ExtractionMonitor(DEFAULT_OUTPUT_DIR, output_file)
    
    try:
        # Set up the command with Popen instead of run
        # Use UTF-8 encoding to handle non-ASCII characters
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace'  # Replace invalid characters rather than failing
        )
        
        # Start monitoring
        monitor.start(process)
        
        # Set up signal handlers for graceful termination
        original_sigint = signal.getsignal(signal.SIGINT)
        
        def signal_handler(sig, frame):
            print("\nReceived termination signal. Cleaning up...")
            monitor.stop()
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
            signal.signal(signal.SIGINT, original_sigint)
            sys.exit(1)
        
        signal.signal(signal.SIGINT, signal_handler)
        
        # Wait for process to complete
        stdout, stderr = process.communicate()
        
        # Stop monitoring
        monitor.stop()
        
        # Process complete, check result
        if process.returncode == 0:
            print(f"\nExtraction completed successfully in {monitor.get_elapsed_time():.1f} seconds")
            
            # Check if output file exists
            output_path = DEFAULT_OUTPUT_DIR / output_file
            if output_path.exists():
                print(f"Output saved to: {output_path}")
                return {
                    "status": "success",
                    "output_file": str(output_path),
                    "duration": monitor.get_elapsed_time(),
                    "stdout": stdout,
                    "stderr": stderr,
                }
            else:
                print(f"Warning: Process completed but output file not found at {output_path}")
                return {
                    "status": "warning",
                    "message": "Process completed but output file not found",
                    "stdout": stdout,
                    "stderr": stderr,
                }
        else:
            print(f"\nExtraction failed with exit code {process.returncode}")
            print(f"Error message: {stderr}")
            return {
                "status": "error",
                "message": f"Extraction failed with exit code {process.returncode}",
                "stdout": stdout,
                "stderr": stderr,
            }
    
    except subprocess.TimeoutExpired:
        monitor.stop()
        print("\nError: Process timed out")
        return {"status": "error", "message": "Process timed out"}
    except KeyboardInterrupt:
        monitor.stop()
        print("\nExtraction cancelled by user")
        return {"status": "cancelled", "message": "Cancelled by user"}
    except Exception as e:
        monitor.stop()
        logger.error(f"Error running extraction: {str(e)}")
        print(f"\nError: {str(e)}")
        return {"status": "error", "message": str(e)}
    finally:
        # Restore original signal handler
        signal.signal(signal.SIGINT, original_sigint)

def interactive_mode():
    """Run the CLI in interactive mode."""
    print("\n=== Headless Web Extraction Tool ===\n")
    
    # Get API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        api_key = get_input("Enter your Anthropic API key", required=True)
    else:
        print(f"Using Anthropic API key from environment: {api_key[:4]}...{api_key[-4:]}")
    
    # Get extraction parameters
    url = get_input("Enter the URL to extract data from", required=True)
    
    instructions = get_multiline_input("Enter extraction instructions")
    
    # Extract domain name for normalized filename
    import re
    domain = re.sub(r'^https?://(www\.)?', '', url)
    domain = domain.split('/')[0]
    domain = domain.replace('.', '_')
    
    # Generate normalized filename with datestamp
    from datetime import datetime
    datestamp = datetime.now().strftime("%Y%m%d")
    default_filename = f"{domain}_data_{datestamp}.json"
    
    output_file = get_input("Enter output filename", default=default_filename)
    output_format = get_input("Enter output format (json, csv, txt)", default=DEFAULT_FORMAT)
    
    # Confirm before running
    print("\nReview your extraction settings:")
    print(f"URL: {url}")
    print(f"Instructions: {instructions[:50]}..." if len(instructions) > 50 else f"Instructions: {instructions}")
    print(f"Output: {output_file}")
    print(f"Format: {output_format}")
    
    confirm = get_input("Proceed with extraction? (y/n)", default="y")
    if confirm.lower() != "y":
        print("Extraction cancelled.")
        return
    
    # Run the extraction
    print("\nStarting extraction. This may take a while...\n")
    result = run_extraction(url, instructions, output_file, output_format, api_key)
    
    # Show the result
    if result["status"] == "success":
        print(f"\nExtraction completed successfully!")
        print(f"Output saved to: {result['output_file']}")
        print(f"Duration: {result['duration']:.2f} seconds")
    else:
        print(f"\nExtraction {result['status']}: {result.get('message', 'Unknown error')}")
        print("Check the logs for more details.")

def cli_mode():
    """Run the CLI in command line mode with arguments."""
    parser = argparse.ArgumentParser(description="Headless Web Extraction Tool")
    parser.add_argument("--url", required=True, help="URL to extract data from")
    parser.add_argument("--instructions", required=True, help="Instructions for extraction")
    parser.add_argument("--output", help="Output filename")
    parser.add_argument("--format", default=DEFAULT_FORMAT, choices=["json", "csv", "txt"], help="Output format")
    parser.add_argument("--api-key", help="Anthropic API key")
    
    args = parser.parse_args()
    
    # Extract domain name for normalized filename
    import re
    domain = re.sub(r'^https?://(www\.)?', '', args.url)
    domain = domain.split('/')[0]
    domain = domain.replace('.', '_')
    
    # Generate normalized filename with datestamp
    from datetime import datetime
    datestamp = datetime.now().strftime("%Y%m%d")
    
    # Generate default filename if not provided
    if not args.output:
        args.output = f"{domain}_data_{datestamp}.json"
    
    # Run the extraction
    result = run_extraction(args.url, args.instructions, args.output, args.format, args.api_key)
    
    # Return appropriate exit code
    if result["status"] == "success":
        print(f"Extraction completed successfully. Output saved to: {result['output_file']}")
        return 0
    else:
        print(f"Extraction {result['status']}: {result.get('message', 'Unknown error')}")
        return 1

if __name__ == "__main__":
    try:
        # Check if running in interactive or cli mode
        if len(sys.argv) > 1:
            sys.exit(cli_mode())
        else:
            interactive_mode()
    except KeyboardInterrupt:
        print("\nExecution cancelled by user")
        sys.exit(1)