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
import platform
from datetime import datetime
from pathlib import Path
import logging
from typing import Tuple
import asyncio

from headless_browser.headless_extractor import HeadlessExtractor

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
        self.shared_dir = shared_dir if isinstance(shared_dir, Path) else Path(shared_dir)
        self.output_file = output_file
        self.status_file = self.shared_dir / "container_status.txt"
        self.running = False
        self.start_time = None
        self.process = None
        self.has_problem = False
        self.problem_text = ""
        self.last_status = ""
        
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
                try:
                    status = container_status_file.read_text(errors='replace')
                    self.last_status = status
                    
                    # Check for problems
                    if "I HAVE A PROBLEM:" in status:
                        self.has_problem = True
                        self.problem_text = status.split("I HAVE A PROBLEM:")[1].split("(")[0].strip()
                        print(f"\n\n⚠️ PROBLEM DETECTED: {self.problem_text}")
                        # Prompt for additional instructions
                        additional_instructions = input("\nEnter additional instructions to help Claude (or just press Enter to continue): ")
                        if additional_instructions:
                            # For now, just log that we would handle this
                            # In a real implementation, we'd need a way to send this to the running container
                            print(f"\nAdditional instructions would be sent: {additional_instructions}")
                    
                    self._write_status(status)
                except Exception as e:
                    logger.error(f"Error reading status file: {e}")
            else:
                # No status file from container, show general status
                elapsed = time.time() - self.start_time
                spinner_char = spinner[spinner_idx]
                spinner_idx = (spinner_idx + 1) % len(spinner)
                
                status = f"{spinner_char} Extraction in progress ({elapsed:.0f}s elapsed)"
                dots = (dots + 1) % 4
                self._write_status(status + "." * dots)
            
            # Also capture process stdout/stderr for additional feedback
            try:
                stdout_line = self.process.stdout.readline().strip()
                if stdout_line:
                    logger.info(f"Container stdout: {stdout_line}")
                    print(f"\r{stdout_line}".ljust(80))
                
                stderr_line = self.process.stderr.readline().strip()
                if stderr_line:
                    logger.warning(f"Container stderr: {stderr_line}")
                    print(f"\r⚠️ {stderr_line}".ljust(80))
            except Exception as e:
                logger.debug(f"Error reading process output: {e}")
            
            time.sleep(1)  # Check more frequently
    
    def _write_status(self, status):
        """Write status to status file and terminal."""
        if self.status_file.parent.exists():
            try:
                with open(self.status_file, 'w', encoding='utf-8') as f:
                    f.write(status)
            except Exception as e:
                logger.error(f"Error writing status file: {e}")
        
        # Format the status message for console
        elapsed = time.time() - self.start_time if self.start_time else 0
        
        # Format output with colors for success/error
        if "SUCCESSFULLY COMPLETED:" in status:
            status_line = f"\r[{elapsed:.0f}s] ✅ {status.replace('SUCCESSFULLY COMPLETED:', '').split('(')[0].strip()}"
        elif "I HAVE A PROBLEM:" in status:
            status_line = f"\r[{elapsed:.0f}s] ❌ {status.replace('I HAVE A PROBLEM:', '').split('(')[0].strip()}"
        elif "PROGRESS UPDATE:" in status:
            status_line = f"\r[{elapsed:.0f}s] 🔄 {status.replace('PROGRESS UPDATE:', '').split('(')[0].strip()}"
        else:
            status_line = f"\r[{elapsed:.0f}s] {status.split('(')[0].strip()}"
        
        sys.stdout.write(status_line.ljust(120))
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

def normalize_domain(url: str) -> str:
    """Normalize domain name by removing protocol and www, replacing dots with underscores."""
    # Remove protocol if present
    domain = re.sub(r'^https?://', '', url)
    # Remove www. if present
    domain = re.sub(r'^www\.', '', domain)
    # Get the domain part (before any path)
    domain = domain.split('/')[0]
    # Replace dots with underscores for directory name
    return domain.replace('.', '_')

def create_output_path(domain: str, output_format: str) -> Tuple[Path, str]:
    """Create output directory and generate standardized filename."""
    # Create domain directory in shared folder
    domain_dir = DEFAULT_OUTPUT_DIR / domain
    domain_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate filename with datestamp and type
    datestamp = datetime.now().strftime("%Y%m%d")
    datatype = "screenshot" if output_format.lower() in ['png', 'jpg', 'jpeg'] else "data"
    filename = f"{datestamp}_{datatype}.{output_format}"
    
    return domain_dir, filename

def create_docker_command(url, instructions, output_path, output_format, api_key=None):
    """Create Docker command for extraction."""
    # Normalize URL
    url = normalize_url(url)
    
    # Ensure output directory exists
    output_dir = DEFAULT_OUTPUT_DIR
    output_dir.mkdir(exist_ok=True)
    
    # Extract domain and filename parts from the output_path
    # output_path might be something like "shared/example_com/20250320_data.json"
    domain = Path(output_path).parent.name
    filename = Path(output_path).name
    
    # Prepare Docker command
    cmd = [
        "docker", "run", "--rm",
        "-e", "HEADLESS_MODE=true",
        "-e", f"EXTRACTION_URL={url}",
        "-e", f"EXTRACTION_INSTRUCTIONS={instructions}",
        "-e", f"EXTRACTION_OUTPUT=/home/computeruse/shared/{domain}/{filename}",
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
    
    # Use cross-platform path syntax
    home_dir = Path.home()
    current_dir = Path.cwd()
    
    # Detect platform and use appropriate path syntax
    if platform.system() == "Windows":
        cmd.extend([
            "-v", f"{current_dir}\\shared:/home/computeruse/shared",
            "-v", f"{home_dir}\\.anthropic:/home/computeruse/.anthropic",
        ])
    else:
        # Unix-style paths for Linux/macOS
        cmd.extend([
            "-v", f"{current_dir}/shared:/home/computeruse/shared",
            "-v", f"{home_dir}/.anthropic:/home/computeruse/.anthropic",
        ])
    
    # Add image name
    cmd.append("headless-browser:latest")  # Use our local image
    
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
        print("\n🚀 Starting container for headless extraction...")
        
        # Set up the command with Popen
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace',
            bufsize=1,  # Line buffered for real-time output
        )
        
        print(f"📦 Container started with ID: {process.pid}")
        
        # Start monitoring
        monitor.start(process)
        
        # Set up signal handlers for graceful termination
        original_sigint = signal.getsignal(signal.SIGINT)
        
        def signal_handler(sig, frame):
            print("\n\n🛑 Received termination signal. Cleaning up...")
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
            print(f"\n\n✅ Extraction completed successfully in {monitor.get_elapsed_time():.1f} seconds")
            
            # Check if output file exists
            output_path = DEFAULT_OUTPUT_DIR / output_file
            if Path(str(output_path).replace('\\', '/')).exists():
                print(f"📄 Output saved to: {output_path}")
                return {
                    "status": "success",
                    "output_file": str(output_path),
                    "duration": monitor.get_elapsed_time(),
                    "stdout": stdout,
                    "stderr": stderr,
                }
            else:
                print(f"⚠️ Warning: Process completed but output file not found at {output_path}")
                return {
                    "status": "warning",
                    "message": "Process completed but output file not found",
                    "stdout": stdout,
                    "stderr": stderr,
                }
        else:
            print(f"\n\n❌ Extraction failed with exit code {process.returncode}")
            print(f"Error message: {stderr}")
            return {
                "status": "error",
                "message": f"Extraction failed with exit code {process.returncode}",
                "stdout": stdout,
                "stderr": stderr,
            }
    
    except subprocess.TimeoutExpired:
        monitor.stop()
        print("\n\n⏱️ Error: Process timed out")
        return {"status": "error", "message": "Process timed out"}
    except KeyboardInterrupt:
        monitor.stop()
        print("\n\n🛑 Extraction cancelled by user")
        return {"status": "cancelled", "message": "Cancelled by user"}
    except Exception as e:
        monitor.stop()
        logger.error(f"Error running extraction: {str(e)}")
        print(f"\n\n❌ Error: {str(e)}")
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
    
    # Normalize domain and create output directory
    domain = normalize_domain(url)
    output_format = get_input(
        "Enter output format (json, csv, txt, png, jpg, jpeg)", 
        default=DEFAULT_FORMAT
    )
    
    # Create output directory and generate filename
    domain_dir, filename = create_output_path(domain, output_format)
    output_file = str(domain_dir / filename)
    
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
    parser.add_argument(
        "--output",
        help="Output filename (optional, will be auto-generated if not provided)"
    )
    parser.add_argument(
        "--type",
        choices=["data", "screenshot"],
        default="data",
        help="Type of extraction (data=JSON, screenshot=PNG)"
    )
    parser.add_argument(
        "--api-key",
        help="API key (if not set in environment)"
    )
    
    args = parser.parse_args()
    
    # Generate default output path if not provided
    if not args.output:
        args.output = get_default_output_path(args.url, args.type)
    
    # Create extractor
    extractor = HeadlessExtractor(
        url=args.url,
        extraction_instructions=args.instructions,
        output_file=args.output,
        is_screenshot=args.type == "screenshot",
        api_key=args.api_key
    )
    
    # Run extraction
    try:
        asyncio.run(extractor.run())
    except KeyboardInterrupt:
        print("\nExtraction cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nError during extraction: {e}")
        sys.exit(1)

def get_default_output_path(url: str, extraction_type: str) -> str:
    """Generate a default output path based on URL and extraction type."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    extension = "png" if extraction_type == "screenshot" else "json"
    return f"shared/{timestamp}_{url.replace('://', '_').replace('/', '_')}.{extension}"

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