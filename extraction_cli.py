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
from typing import Tuple, Optional
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
        """Main monitoring loop with enhanced inactivity detection."""
        dots = 0
        spinner = ["|", "/", "-", "\\"]
        spinner_idx = 0
        last_status_update = time.time()
        inactivity_warning_shown = False
        
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
                    if status != self.last_status:
                        last_status_update = time.time()
                        self.last_status = status
                        inactivity_warning_shown = False
                    
                    # Check for inactivity (no status updates for 2 minutes)
                    if time.time() - last_status_update > 120 and not inactivity_warning_shown:
                        print(f"\n\n⚠️ WARNING: No status updates for {int(time.time() - last_status_update)} seconds.")
                        print("The extraction process may be stalled. Consider terminating (Ctrl+C) and restarting.")
                        inactivity_warning_shown = True
                    
                    # Check for problems
                    if "I HAVE A PROBLEM:" in status:
                        self.has_problem = True
                        self.problem_text = status.split("I HAVE A PROBLEM:")[1].split("(")[0].strip()
                        print(f"\n\n⚠️ PROBLEM DETECTED: {self.problem_text}")
                        # Prompt for additional instructions
                        additional_instructions = input("\nEnter additional instructions to help Claude (or just press Enter to continue): ")
                        if additional_instructions:
                            # For now, just log that we would handle this
                            print(f"\nAdditional instructions would be sent: {additional_instructions}")
                    
                    self._write_status(status)
                except Exception as e:
                    logger.error(f"Error reading status file: {e}")
            else:
                # No status file from container, show general status
                elapsed = time.time() - self.start_time
                spinner_char = spinner[spinner_idx]
                spinner_idx = (spinner_idx + 1) % len(spinner)
                
                # Check for container creation inactivity (no status file after 60s)
                if elapsed > 60 and not container_status_file.exists() and not inactivity_warning_shown:
                    print(f"\n\n⚠️ WARNING: No status file created after {int(elapsed)} seconds.")
                    print("The container may not be initializing correctly. Check Docker logs.")
                    inactivity_warning_shown = True
                
                status = f"{spinner_char} Extraction in progress ({elapsed:.0f}s elapsed)"
                dots = (dots + 1) % 4
                self._write_status(status + "." * dots)
            
            # Process stdout/stderr
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

def find_output_file(base_path: Path, filename: str, search_subdirs: bool = True) -> Optional[Path]:
    """Search for output file in various potential locations."""
    # Check exact path
    if base_path.exists():
        return base_path
        
    # Check filename only in shared dir
    shared_path = DEFAULT_OUTPUT_DIR / filename
    if shared_path.exists():
        return shared_path
        
    # Check for file in domain directories
    if search_subdirs:
        for subdir in DEFAULT_OUTPUT_DIR.iterdir():
            if subdir.is_dir():
                potential_path = subdir / filename
                if potential_path.exists():
                    return potential_path
                    
    # Try a glob pattern search
    pattern = f"**/{filename}"
    matches = list(DEFAULT_OUTPUT_DIR.glob(pattern))
    if matches:
        return matches[0]
        
    return None

def print_docker_logs(container_name: str):
    """Print logs from a Docker container to help with debugging."""
    try:
        print("\n=== Docker Container Logs ===")
        subprocess.run(["docker", "logs", container_name], check=False)
        print("=== End of Docker Logs ===\n")
    except Exception as e:
        print(f"Error retrieving Docker logs: {e}")

def create_output_path(domain: str, output_format: str) -> Tuple[Path, str]:
    """Create output directory and generate standardized filename."""
    # Create domain directory in shared folder
    domain_dir = DEFAULT_OUTPUT_DIR / domain
    domain_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate filename with datestamp and type
    datestamp = datetime.now().strftime("%Y%m%d")
    datatype = "screenshot" if output_format.lower() in ['png', 'jpg', 'jpeg'] else "data"
    filename = f"{datestamp}_{datatype}.{output_format}"
    
    # Return domain_dir relative to shared directory
    return domain_dir, filename

def create_docker_command(url, instructions, output_path, output_format, api_key=None, use_remote_image=False):
    """Create Docker command for extraction with improved volume mounting and timeout."""
    # Normalize URL
    url = normalize_url(url)
    
    # Ensure output directory exists
    output_dir = DEFAULT_OUTPUT_DIR
    output_dir.mkdir(exist_ok=True)
    
    # Extract domain and filename parts from the output_path
    domain = Path(output_path).parent.name
    filename = Path(output_path).name
    
    # Determine extraction type
    extraction_type = "screenshot" if output_format.lower() in ['png', 'jpg', 'jpeg'] else "data"
    
    # Prepare Docker command
    cmd = [
        "docker", "run", "--rm",
    ]
    
    # Add container naming for easier tracking
    container_name = f"headless-extraction-{int(time.time())}"
    cmd.extend([
        "--name", container_name,
    ])
    
    # Add hard timeout of 10 minutes (600 seconds) to the Docker run command
    cmd.extend(["--stop-timeout", "600"])
    
    # Add API key if provided
    if api_key:
        cmd.extend(["-e", f"ANTHROPIC_API_KEY={api_key}"])
    else:
        # Try to get from environment
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if api_key:
            cmd.extend(["-e", f"ANTHROPIC_API_KEY={api_key}"])
    
    # Use absolute paths for volume mounting to avoid path resolution issues
    shared_dir = Path(DEFAULT_OUTPUT_DIR).absolute()
    home_dir = Path.home().absolute()
    
    # Use consistent forward slashes for Docker paths
    shared_docker_path = str(shared_dir).replace('\\', '/')
    home_docker_path = str(home_dir).replace('\\', '/')
    
    # Add extended volume mounts with consistent formatting
    cmd.extend([
        "-v", f"{shared_docker_path}:/home/computeruse/shared",
        "-v", f"{home_docker_path}/.anthropic:/home/computeruse/.anthropic",
    ])
    
    # Add image name
    if use_remote_image:
        cmd.append("ghcr.io/anthropics/anthropic-quickstarts:computer-use-demo-latest")
    else:
        cmd.append("headless-browser:latest")
        
    # Override entrypoint to directly call the Python script with the correct arguments
    cmd.extend([
        "python", "-m", "headless_browser.headless_extractor",
        "--url", url,
        "--instructions", instructions,
        "--output", f"/home/computeruse/shared/{domain}/{filename}",
        "--type", extraction_type,
        "--provider", API_PROVIDER,
        "--model", DEFAULT_MODEL,
        "--tool-version", "computer_use_20250124"
    ])
    
    return cmd, container_name  # Return both the command and container name

def run_extraction(url, instructions, output_file, output_format, api_key=None, use_remote_image=False):
    """Run the headless extraction using Docker."""
    # Prepare command
    cmd, container_name = create_docker_command(url, instructions, output_file, output_format, api_key, use_remote_image)
    
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
            cleanup_container(container_name)
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
            
            # Use the new find_output_file function to locate the output
            output_path = Path(output_file)
            found_path = find_output_file(output_path, output_path.name)
            
            if found_path:
                print(f"📄 Output saved to: {found_path}")
                return {
                    "status": "success",
                    "output_file": str(found_path),
                    "duration": monitor.get_elapsed_time(),
                    "stdout": stdout,
                    "stderr": stderr,
                }
            else:
                print(f"⚠️ Warning: Process completed but output file not found")
                print_docker_logs(container_name)  # Print logs to help debug
                return {
                    "status": "warning",
                    "message": "Process completed but output file not found",
                    "stdout": stdout,
                    "stderr": stderr,
                }
        else:
            print(f"\n\n❌ Extraction failed with exit code {process.returncode}")
            print(f"Error message: {stderr}")
            print_docker_logs(container_name)  # Print logs to help debug
            return {
                "status": "error",
                "message": f"Extraction failed with exit code {process.returncode}",
                "stdout": stdout,
                "stderr": stderr,
            }
    
    except subprocess.TimeoutExpired:
        print("\n\n⏱️ Error: Process timed out")
        print_docker_logs(container_name)  # Print logs to help debug
        cleanup_container(container_name)
        monitor.stop()
        return {"status": "error", "message": "Process timed out"}
    except KeyboardInterrupt:
        print("\n\n🛑 Extraction cancelled by user")
        cleanup_container(container_name)
        monitor.stop()
        return {"status": "cancelled", "message": "Cancelled by user"}
    except Exception as e:
        print(f"\n\n❌ Error: {str(e)}")
        print_docker_logs(container_name)  # Print logs to help debug
        cleanup_container(container_name)
        monitor.stop()
        logger.error(f"Error running extraction: {str(e)}")
        return {"status": "error", "message": str(e)}
    finally:
        # Restore original signal handler
        signal.signal(signal.SIGINT, original_sigint)
        # Ensure container is cleaned up
        cleanup_container(container_name)

def cleanup_container(container_name: str):
    """Clean up Docker container and associated resources."""
    try:
        # Try to stop the container gracefully first
        subprocess.run(["docker", "stop", container_name], check=False, capture_output=True)
        # Remove the container
        subprocess.run(["docker", "rm", "-f", container_name], check=False, capture_output=True)
        logger.info(f"Successfully cleaned up container: {container_name}")
    except Exception as e:
        logger.error(f"Error cleaning up container {container_name}: {e}")

def get_default_output_path(url: str, extraction_type: str) -> str:
    """Generate a default output path based on URL and extraction type."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    extension = "png" if extraction_type == "screenshot" else "json"
    return f"shared/{timestamp}_{url.replace('://', '_').replace('/', '_')}.{extension}"

def check_docker_image():
    """Check if the Docker image exists and offer to build it if not."""
    try:
        result = subprocess.run(
            ["docker", "images", "headless-browser:latest", "--format", "{{.Repository}}"],
            check=True,
            capture_output=True,
            text=True
        )
        
        if "headless-browser" in result.stdout:
            print("✅ Docker image 'headless-browser:latest' found")
            return True
        else:
            print("⚠️ Docker image 'headless-browser:latest' not found")
            build = input("Do you want to build the Docker image now? (y/n): ").lower() == 'y'
            
            if build:
                # Run the build script
                try:
                    # Check if build script exists
                    build_script = Path("build_docker_image.py")
                    if not build_script.exists():
                        # Create the build script
                        with open(build_script, "w") as f:
                            f.write("""#!/usr/bin/env python3
\"\"\"
Docker image builder for headless extraction.
This script builds the Docker image required for headless extraction.
\"\"\"

import subprocess
import os
import sys
import time
from pathlib import Path
import platform

def check_docker_installed():
    \"\"\"Check if Docker is installed and running.\"\"\"
    try:
        subprocess.run(["docker", "info"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print("✅ Docker is installed and running")
        return True
    except subprocess.CalledProcessError:
        print("❌ Docker is not running or not accessible")
        print("Please start Docker and try again")
        return False
    except FileNotFoundError:
        print("❌ Docker is not installed")
        print("Please install Docker and try again")
        return False

def build_image():
    \"\"\"Build the Docker image for headless extraction.\"\"\"
    print("\\n=== Building Docker Image for Headless Extraction ===\\n")
    
    # Check Docker installation
    if not check_docker_installed():
        return False
    
    # Check for existing image
    try:
        result = subprocess.run(
            ["docker", "images", "headless-browser:latest", "--format", "{{.Repository}}"],
            check=True,
            capture_output=True,
            text=True
        )
        
        if "headless-browser" in result.stdout:
            print("ℹ️ Found existing 'headless-browser:latest' image")
            rebuild = input("Do you want to rebuild the image anyway? (y/n): ").lower() == 'y'
            if not rebuild:
                print("✅ Using existing image")
                return True
    except Exception as e:
        print(f"Warning when checking for existing image: {e}")
    
    print("\\n1. Building from local Dockerfile...")
    
    # Build from Dockerfile in current directory
    try:
        start_time = time.time()
        
        # Use build command with output streaming
        process = subprocess.Popen(
            ["docker", "build", "-t", "headless-browser:latest", "."],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        # Stream output
        print("\\nBuild output:")
        print("-" * 50)
        
        for line in process.stdout:
            print(line.strip())
        
        # Wait for process to complete
        process.wait()
        
        if process.returncode == 0:
            build_time = time.time() - start_time
            print("-" * 50)
            print(f"✅ Successfully built local image in {build_time:.1f} seconds")
            return True
        else:
            print("-" * 50)
            print("❌ Failed to build image from local Dockerfile")
            
            # Try alternative: pull from remote
            return pull_remote_image()
    
    except Exception as e:
        print(f"❌ Error building image: {e}")
        return pull_remote_image()

def pull_remote_image():
    \"\"\"Pull the image from GitHub container registry as a fallback.\"\"\"
    print("\\n2. Trying to pull image from GitHub Container Registry...")
    
    try:
        # Try to pull from GitHub Container Registry
        process = subprocess.Popen(
            ["docker", "pull", "ghcr.io/anthropics/anthropic-quickstarts:computer-use-demo-latest"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        # Stream output
        for line in process.stdout:
            print(line.strip())
        
        # Wait for process to complete
        process.wait()
        
        if process.returncode == 0:
            print("✅ Successfully pulled remote image")
            
            # Tag the image
            subprocess.run(
                ["docker", "tag", "ghcr.io/anthropics/anthropic-quickstarts:computer-use-demo-latest", "headless-browser:latest"],
                check=True
            )
            
            print("✅ Tagged remote image as 'headless-browser:latest'")
            return True
        else:
            print("❌ Failed to pull remote image")
            return False
    
    except Exception as e:
        print(f"❌ Error pulling remote image: {e}")
        return False

def main():
    \"\"\"Main function.\"\"\"
    print("\\n🐳 Docker Image Builder for Headless Extraction\\n")
    
    # Create shared directory
    shared_dir = Path("./shared")
    shared_dir.mkdir(exist_ok=True)
    print(f"✅ Ensured shared directory exists at {shared_dir.absolute()}")
    
    # Build or pull the image
    success = build_image()
    
    if success:
        print("\\n✅ Docker image 'headless-browser:latest' is ready to use")
        print("\\nYou can now run the extraction tool:")
        print("    python extraction_cli.py")
        return 0
    else:
        print("\\n❌ Failed to prepare Docker image")
        print("Please check Docker installation and try again")
        return 1

if __name__ == "__main__":
    sys.exit(main())
""")
                        build_script.chmod(0o755)
                    
                    # Run the build script
                    print("\nRunning build script...")
                    subprocess.run([sys.executable, str(build_script)], check=True)
                    
                    # Check if build was successful
                    return check_docker_image()
                except Exception as e:
                    print(f"❌ Error running build script: {e}")
                    return False
            else:
                print("⚠️ Will try to use remote image instead")
                return False
    except Exception as e:
        print(f"❌ Error checking for Docker image: {e}")
        print("⚠️ Will try to use remote image instead")
        return False

def interactive_mode():
    """Run the CLI in interactive mode with simplified output options."""
    print("\n=== Headless Web Extraction Tool ===\n")
    
    # Check if Docker is installed and running
    try:
        subprocess.run(["docker", "info"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ Docker is not running or not installed")
        print("Please install and start Docker, then try again")
        return
    
    # Check for Docker image and offer to build if needed
    has_local_image = check_docker_image()
    
    # Get API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        api_key = get_input("Enter your Anthropic API key", required=True)
    else:
        print(f"Using Anthropic API key from environment: {api_key[:4]}...{api_key[-4:]}")
    
    # Get extraction parameters
    url = get_input("Enter the URL to extract data from", required=True)
    instructions = get_multiline_input("Enter extraction instructions")
    
    # Determine extraction type based on instructions
    is_screenshot = "screenshot" in instructions.lower() or "image" in instructions.lower()
    extraction_type = "screenshot" if is_screenshot else "data"
    output_format = "png" if is_screenshot else "json"
    
    # Normalize domain and create output directory
    domain = normalize_domain(url)
    
    # Create output directory and generate filename
    domain_dir, filename = create_output_path(domain, output_format)
    output_file = str(domain_dir / filename)
    
    # Confirm before running
    print("\nReview your extraction settings:")
    print(f"URL: {url}")
    print(f"Instructions: {instructions[:50]}..." if len(instructions) > 50 else f"Instructions: {instructions}")
    print(f"Output: {output_file}")
    print(f"Type: {extraction_type.capitalize()} extraction ({output_format.upper()})")
    print(f"Using {'local' if has_local_image else 'remote'} Docker image")
    
    confirm = get_input("Proceed with extraction? (y/n)", default="y")
    if confirm.lower() != "y":
        print("Extraction cancelled.")
        return
    
    # Run the extraction
    print("\nStarting extraction. This may take a while...\n")
    result = run_extraction(url, instructions, output_file, output_format, api_key, not has_local_image)
    
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
    parser.add_argument(
        "--use-remote-image",
        action="store_true",
        help="Use remote Docker image instead of local"
    )
    
    args = parser.parse_args()
    
    # Generate default output path if not provided
    if not args.output:
        args.output = get_default_output_path(args.url, args.type)
    
    # Run the extraction
    try:
        print(f"\nStarting extraction from {args.url}")
        print(f"Docker image: {'Remote' if args.use_remote_image else 'Local'}")
        
        result = run_extraction(
            url=args.url,
            instructions=args.instructions,
            output_file=args.output,
            output_format="png" if args.type == "screenshot" else "json",
            api_key=args.api_key,
            use_remote_image=args.use_remote_image
        )
        
        # Show the result
        if result["status"] == "success":
            print(f"\nExtraction completed successfully!")
            print(f"Output saved to: {result['output_file']}")
            print(f"Duration: {result['duration']:.2f} seconds")
        else:
            print(f"\nExtraction {result['status']}: {result.get('message', 'Unknown error')}")
            print("Check the logs for more details.")
            
    except KeyboardInterrupt:
        print("\nExtraction cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nError during extraction: {e}")
        sys.exit(1)

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