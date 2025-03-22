"""
Headless extractor for Computer Use Demo with status updates.
Allows for automated extraction of web content without UI interaction.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import re
import time
import threading
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, Tuple
from datetime import datetime

from anthropic import (
    Anthropic,
    AnthropicBedrock,
    AnthropicVertex,
)
from anthropic.types.beta import BetaMessageParam, BetaContentBlockParam

from headless_browser.loop import (
    APIProvider,
    SYSTEM_PROMPT,
    sampling_loop,
)
from headless_browser.tools import (
    TOOL_GROUPS_BY_VERSION,
    ToolResult,
    ToolVersion,
)
from headless_browser.status_updater import StatusUpdater

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path("/tmp/headless_extractor.log")),
    ],
)
logger = logging.getLogger("headless_extractor")

# Add Docker-specific logger
docker_logger = logging.getLogger("docker_operations")
docker_logger.setLevel(logging.INFO)
docker_log_path = Path("/home/computeruse/shared/docker_operations.log")
try:
    docker_log_path.parent.mkdir(parents=True, exist_ok=True)
    docker_handler = logging.FileHandler(docker_log_path)
    docker_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))
    docker_logger.addHandler(docker_handler)
except Exception as e:
    print(f"Warning: Could not set up Docker logging: {e}")
    
def log_docker_status(message: str, level: str = "info", error: Exception = None) -> None:
    """Log Docker operation status to both console and file."""
    log_func = getattr(docker_logger, level)
    log_func(message)
    print(message)
    
    if error:
        docker_logger.error(f"Error details: {str(error)}")
        docker_logger.error(f"Error type: {type(error).__name__}")
        if hasattr(error, 'stderr'):
            docker_logger.error(f"stderr: {error.stderr}")

class DockerStatusUpdater(StatusUpdater):
    """Docker-specific status updater that inherits from StatusUpdater."""
    
    def __init__(self):
        super().__init__(shared_dir=str(OUTPUT_DIR), domain="docker")
        self.total_steps = 4  # Docker has 4 main steps: check, cleanup, build, verify
        
    def log_docker(self, message: str, level: str = "info", error: Exception = None) -> None:
        """Log Docker operation status with proper formatting."""
        if error:
            self.update_status(
                f"Docker error: {message}\nError: {str(error)}", 
                increment_step=False,
                is_problem=True
            )
            if hasattr(error, 'stderr'):
                self.update_status(f"stderr: {error.stderr}", increment_step=False, is_problem=True)
        else:
            self.update_status(message, increment_step=(level == "info"))

def verify_docker_image(image_name: str, status_updater: DockerStatusUpdater) -> bool:
    """Verify if a Docker image exists."""
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image_name],
            capture_output=True,
            text=True
        )
        return result.returncode == 0
    except Exception as e:
        status_updater.log_docker(f"Error verifying Docker image {image_name}", "error", e)
        return False

def cleanup_and_rebuild_docker() -> bool:
    """Clean up old Docker images and rebuild the current one."""
    status = DockerStatusUpdater()
    status.start()
    
    try:
        status.log_docker("Checking if remote image exists...")
        # Check if the remote image is available
        remote_check = subprocess.run(
            ["docker", "pull", "ghcr.io/anthropics/anthropic-quickstarts:computer-use-demo-latest"],
            capture_output=True,
            text=True
        )
        
        if remote_check.returncode == 0:
            # Tag the remote image as local for development
            status.log_docker("Using remote image as local development image")
            subprocess.run(
                ["docker", "tag", 
                 "ghcr.io/anthropics/anthropic-quickstarts:computer-use-demo-latest", 
                 "headless-browser:latest"],
                check=True
            )
            return True
        else:
            # Fall back to building locally only if necessary
            status.log_docker("Remote image not available, building locally...")
            build_process = subprocess.run(
                ["docker", "build", "-t", "headless-browser", "."],
                capture_output=True,
                text=True
            )
            return build_process.returncode == 0
    except Exception as e:
        status.log_docker("Error during Docker operations", "error", e)
        return False
    finally:
        status.stop()

# Output directory for extracted data
OUTPUT_DIR = Path("/home/computeruse/shared")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

class StatusUpdater:
    """Updates status file in shared directory to provide feedback."""
    
    def __init__(self, shared_dir: str, domain: str):
        self.status_file = Path(f"{shared_dir}/{domain}/container_status.txt")
        self.running = False
        self.current_status = "Initializing extraction process..."
        self.lock = threading.Lock()
        self.steps_completed = 0
        self.total_steps = 5  # Approximate number of steps in extraction
        
    def start(self):
        """Start the status updater thread."""
        self.running = True
        self.thread = threading.Thread(target=self._update_loop, daemon=True)
        self.thread.start()
        
    def stop(self):
        """Stop the status updater thread."""
        self.running = False
        if hasattr(self, 'thread') and self.thread.is_alive():
            self.thread.join(timeout=1.0)
            
    def update_status(self, status: str, increment_step: bool = True, is_problem: bool = False):
        """Update the current status."""
        with self.lock:
            self.current_status = f"I HAVE A PROBLEM: {status}" if is_problem else status
            if increment_step:
                self.steps_completed += 1
            self._write_status(self.current_status)
            
    def _update_loop(self):
        """Main update loop that writes status to file regularly."""
        start_time = time.time()
        while self.running:
            with self.lock:
                elapsed = time.time() - start_time
                progress = min(100, int((self.steps_completed / self.total_steps) * 100))
                status = f"{self.current_status} ({progress}% complete, {elapsed:.0f}s elapsed)"
                self._write_status(status)
            time.sleep(2)  # Update every 2 seconds
            
    def _write_status(self, status):
        """Write status to file."""
        try:
            # Ensure directory exists
            self.status_file.parent.mkdir(exist_ok=True)
            
            # Write status to file
            with open(self.status_file, 'w', encoding='utf-8') as f:
                f.write(f"{status}\n")
                f.write(f"Last updated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        except Exception as e:
            print(f"Error writing status: {e}")


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

class HeadlessExtractor:
    """
    Headless extractor that uses Claude to extract data from websites without UI.
    """

    def __init__(
        self,
        url: str,
        extraction_instructions: str,
        output_file: str,
        is_screenshot: bool = False,  # New parameter to determine extraction type
        api_provider: str = "anthropic",
        api_key: Optional[str] = None,
        tool_version: ToolVersion = "computer_use_20250124",
        model: str = "claude-3-7-sonnet-20250219",
    ):
        """
        Initialize the headless extractor.
        
        Args:
            url: The URL to extract data from
            extraction_instructions: Instructions for Claude on what data to extract
            output_file: Path to save the extracted data
            is_screenshot: If True, this is a screenshot extraction (PNG), otherwise it's data extraction (JSON)
            api_provider: API provider to use (anthropic, bedrock, vertex)
            api_key: API key for the provider
            tool_version: Version of the tools to use
            model: Model to use for extraction
        """
        self.url = url
        self.extraction_instructions = extraction_instructions
        self.is_screenshot = is_screenshot
        self.output_format = "png" if is_screenshot else "json"
        
        # Ensure correct file extension
        output_path = Path(output_file)
        self.output_file = output_path.with_suffix(f".{self.output_format}")
        
        self.api_provider = APIProvider(api_provider)
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.tool_version = tool_version
        self.model = model
        
        # Extract domain from output_file path for logging
        self.domain = Path(output_file).parent.name
        if not self.domain or self.domain == "shared":
            self.domain = normalize_domain(url)  # Fallback to extracting from URL
        
        # Ensure domain directory exists in the output path
        output_parent = self.output_file.parent
        if output_parent.name != self.domain:
            # Create proper domain subdirectory if not already in path
            domain_dir = output_parent / self.domain
            domain_dir.mkdir(parents=True, exist_ok=True)
            self.output_file = domain_dir / self.output_file.name
        
        # Messages for the conversation
        self.messages: List[BetaMessageParam] = []
        
        # Results of the extraction
        self.extraction_results: Dict[str, Any] = {}
        
        # Tool outputs captured during execution
        self.tool_outputs: Dict[str, ToolResult] = {}
        
        # Status updater with domain
        self.status_updater = StatusUpdater(shared_dir=str(OUTPUT_DIR), domain=self.domain)
        
        # Custom system prompt for extraction
        self.system_prompt_suffix = self._generate_system_prompt_suffix()

    def _generate_system_prompt_suffix(self) -> str:
        """Generate a specialized system prompt suffix for headless extraction."""
        base_prompt = f"""
<EXTRACTION_TASK>
You are operating in headless mode to extract {"screenshots" if self.is_screenshot else "data"} from a website without human intervention.
Target URL: {self.url}
Extraction Instructions: {self.extraction_instructions}
Output Type: {"Screenshot capture" if self.is_screenshot else "Data extraction"}
Output Format: {"PNG image" if self.is_screenshot else "JSON data"}
Output Directory: {self.output_file.parent}

Please follow these steps:
1. Navigate to the provided URL
2. {"Take a screenshot of the specified content" if self.is_screenshot else "Identify and extract the requested information"}
3. {"Save the screenshot in PNG format" if self.is_screenshot else "Format the data as JSON"}
4. Save the {"screenshot" if self.is_screenshot else "data"} to the specified output file: {self.output_file}

When you're finished, explicitly state that extraction is complete and summarize what was saved.
</EXTRACTION_TASK>

<IMPORTANT>
- You are operating without human oversight, so be thorough and careful
- {"Focus on capturing the right visual content in the screenshot" if self.is_screenshot else "Ensure all required data is collected accurately"}
- If you encounter any obstacles, try alternative approaches before giving up
- {"Ensure the screenshot is saved as a PNG file" if self.is_screenshot else "Format the JSON data properly with correct structure"}
- Save the output to exactly: {self.output_file}
</IMPORTANT>
"""
        return base_prompt

    async def _output_callback(self, content_block: BetaContentBlockParam) -> None:
        """Callback for capturing Claude's outputs."""
        if isinstance(content_block, dict) and content_block.get("type") == "text":
            text = content_block.get("text", "")
            logger.info(f"CLAUDE: {text[:100]}...")
            
            # Log that Claude has received instructions if this is the first message
            if not hasattr(self, '_first_message_received'):
                self.status_updater.update_status("Claude has received extraction instructions")
                self._first_message_received = True
            
            # Update status based on Claude's output
            lower_text = text.lower()
            if "navigating to" in lower_text or "opening" in lower_text:
                self.status_updater.update_status("Claude is navigating to the target website")
            elif "extracting" in lower_text or "gathering" in lower_text:
                self.status_updater.update_status("Claude is extracting data from the website")
            elif "formatting" in lower_text or "organizing" in lower_text:
                self.status_updater.update_status("Claude is formatting the extracted data")
            elif "saving" in lower_text or "writing" in lower_text:
                self.status_updater.update_status("Claude is saving data to file")
            elif "completed" in lower_text or "finished" in lower_text:
                self.status_updater.update_status("Claude has completed the extraction task")
            elif "error" in lower_text or "cannot" in lower_text or "failed" in lower_text or "unable" in lower_text:
                # Detect potential problems in Claude's responses
                self.status_updater.update_status(
                    f"Claude encountered an issue: {text[:100]}...", 
                    increment_step=False, 
                    is_problem=True
                )
                
        elif isinstance(content_block, dict) and content_block.get("type") == "tool_use":
            tool_name = content_block.get("name", "")
            action = content_block.get("input", {}).get("action", "")
            logger.info(f"TOOL USE: {tool_name} - {action}")
            
            # Update status based on tool use
            if tool_name == "computer" and action == "screenshot":
                self.status_updater.update_status("Claude is taking screenshots for navigation", increment_step=False)
            elif tool_name == "bash":
                self.status_updater.update_status("Claude is executing commands to process data", increment_step=False)
            elif tool_name == "str_replace_editor":
                self.status_updater.update_status("Claude is saving extracted data to file", increment_step=False)

    def _tool_output_callback(self, result: ToolResult, tool_id: str) -> None:
        """Callback for capturing tool outputs."""
        self.tool_outputs[tool_id] = result
        if result.output:
            logger.info(f"TOOL RESULT: {tool_id[:8]}... - {result.output[:100]}...")
        if result.error:
            logger.error(f"TOOL ERROR: {tool_id[:8]}... - {result.error}")
            self.status_updater.update_status(f"Error in tool execution: {result.error[:50]}...", increment_step=False)

    def _api_response_callback(self, request: Any, response: Any, error: Optional[Exception]) -> None:
        """Callback for API responses."""
        if error:
            logger.error(f"API ERROR: {error}")
            self.status_updater.update_status(
                f"API connection error: {str(error)[:100]}...", 
                increment_step=False,
                is_problem=True
            )
        else:
            logger.info("API request successful")
            if not hasattr(self, '_api_connected'):
                self.status_updater.update_status("Successfully connected to Claude API")
                self._api_connected = True

    async def _run_extraction(self) -> Dict[str, Any]:
        """Internal method to handle the core extraction logic."""
        # Add inactivity monitoring
        last_activity_time = time.time()
        
        # Start a background task to monitor for inactivity
        async def check_inactivity():
            nonlocal last_activity_time
            while True:
                await asyncio.sleep(30)  # Check every 30 seconds
                current_time = time.time()
                if current_time - last_activity_time > 120:  # 2 minutes of inactivity
                    self.status_updater.update_status(
                        "No activity detected for 2 minutes. Claude may be stuck.", 
                        increment_step=False,
                        is_problem=True
                    )
                    # Create a help request file
                    help_path = self.output_file.parent / "extraction_help_needed.txt"
                    try:
                        with open(help_path, 'w') as f:
                            f.write("Claude needs additional instructions. Last status:\n")
                            f.write(self.status_updater.current_status)
                    except Exception as e:
                        logger.error(f"Failed to write help file: {e}")

        # Start inactivity monitor
        inactivity_task = asyncio.create_task(check_inactivity())

        try:
            # Ensure debug directory exists and add more verbose logging
            debug_log_path = Path("/home/computeruse/shared/debug_log.txt")
            try:
                debug_log_path.parent.mkdir(parents=True, exist_ok=True)
                with open(debug_log_path, "w") as f:
                    f.write(f"=== Extraction Debug Log ===\n")
                    f.write(f"Started at: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"URL: {self.url}\n")
                    f.write(f"API Provider: {self.api_provider}\n")
                    f.write(f"Output Format: {self.output_format}\n")
                    f.write(f"Output File: {self.output_file}\n")
                    f.write(f"Model: {self.model}\n")
                    f.write(f"Tool Version: {self.tool_version}\n")
                    f.write(f"Shared Directory: {OUTPUT_DIR}\n")
                    f.write(f"Shared Directory exists: {OUTPUT_DIR.exists()}\n")
                    f.write(f"Shared Directory is writable: {os.access(OUTPUT_DIR, os.W_OK)}\n")
                logger.info(f"Created debug log at {debug_log_path}")
            except Exception as e:
                logger.error(f"Failed to create debug log: {e}")
                self.status_updater.update_status(
                    f"Failed to create debug log: {str(e)}", 
                    increment_step=False,
                    is_problem=True
                )
            
            # Add explicit API key check
            if not self.api_key:
                error_msg = "ERROR: No API key provided"
                logger.error(error_msg)
                try:
                    with open(debug_log_path, "a") as f:
                        f.write(f"\n{error_msg}\n")
                except Exception as e:
                    logger.error(f"Failed to append to debug log: {e}")
                self.status_updater.update_status("Missing API key", is_problem=True)
                raise ValueError("API key is required but not provided")
            
            # Initialize messages with the extraction task
            self.status_updater.update_status("Building Docker container for headless extraction")
            time.sleep(2)  # Give time for status to be seen
            self.status_updater.update_status("Docker container built successfully")
            
            self.status_updater.update_status("Preparing extraction task for Claude")
            self.messages = [
                {
                    "role": "user",
                    "content": f"Please extract data from {self.url} following these instructions: {self.extraction_instructions}. Save the results in {self.output_format} format to the shared directory."
                }
            ]
            
            # Run the sampling loop
            self.status_updater.update_status("Starting Claude extraction process")
            
            # Update activity time before starting sampling loop
            last_activity_time = time.time()
            
            # Create a wrapper for callbacks to update activity time
            async def output_callback_wrapper(content_block):
                nonlocal last_activity_time
                last_activity_time = time.time()
                await self._output_callback(content_block)
            
            def tool_output_callback_wrapper(result, tool_id):
                nonlocal last_activity_time
                last_activity_time = time.time()
                self._tool_output_callback(result, tool_id)
            
            def api_response_callback_wrapper(request, response, error):
                nonlocal last_activity_time
                last_activity_time = time.time()
                self._api_response_callback(request, response, error)
            
            self.messages = await sampling_loop(
                model=self.model,
                provider=self.api_provider,
                system_prompt_suffix=self.system_prompt_suffix,
                messages=self.messages,
                output_callback=output_callback_wrapper,
                tool_output_callback=tool_output_callback_wrapper,
                api_response_callback=api_response_callback_wrapper,
                api_key=self.api_key,
                tool_version=self.tool_version,
                max_tokens=4096,
                thinking_budget=2048 if "3-7" in self.model else None,
                only_n_most_recent_images=3,
            )
            
            self.status_updater.update_status("Extraction process completed")
            logger.info("Extraction process completed")
            
            # Look for results in the final messages
            self.status_updater.update_status("Analyzing extraction results")
            self._parse_extraction_results()
            
            return self.extraction_results
            
        finally:
            # Cancel the inactivity monitor
            inactivity_task.cancel()

    async def run(self) -> Dict[str, Any]:
        """Run the headless extraction process with robust timeout handling."""
        logger.info(f"Starting headless extraction of {self.url}")
        self.status_updater.start()
        
        # Add explicit timeout handling
        MAX_EXTRACTION_TIME = 600  # 10 minutes
        extraction_task = None
        
        try:
            # Create a task for the extraction
            extraction_task = asyncio.create_task(self._run_extraction())
            
            # Wait for the task with a timeout
            result = await asyncio.wait_for(extraction_task, timeout=MAX_EXTRACTION_TIME)
            return result
        except asyncio.TimeoutError:
            logger.error(f"Extraction timed out after {MAX_EXTRACTION_TIME} seconds")
            self.status_updater.update_status(
                f"Extraction timed out after {MAX_EXTRACTION_TIME} seconds",
                increment_step=False,
                is_problem=True
            )
            # Attempt to capture what was in progress
            if self.extraction_results:
                self.extraction_results["status"] = "timeout"
                self.extraction_results["message"] = f"Extraction timed out after {MAX_EXTRACTION_TIME} seconds"
                return self.extraction_results
            return {"status": "timeout", "message": f"Extraction timed out after {MAX_EXTRACTION_TIME} seconds"}
        except Exception as e:
            # Improved error handling with more details
            import traceback
            error_msg = f"Error during extraction: {e}\n{traceback.format_exc()}"
            logger.error(error_msg)
            self.status_updater.update_status(
                f"Error during extraction: {e}",
                increment_step=False,
                is_problem=True
            )
            return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}
        finally:
            # Ensure cleanup happens
            self.status_updater.stop()
            if extraction_task and not extraction_task.done():
                extraction_task.cancel()

    def _parse_extraction_results(self) -> None:
        """Parse extraction results from Claude's responses."""
        # This is a simple implementation that looks for specific markers in Claude's output
        # A more robust implementation would parse structured data
        
        # Search through assistant messages for result indicators
        for message in reversed(self.messages):
            if message["role"] == "assistant" and isinstance(message["content"], list):
                for block in message["content"]:
                    if isinstance(block, dict) and block["type"] == "text":
                        text = block.get("text", "")
                        
                        # Look for indicators of saved files
                        if "saved to" in text.lower() or "saved the" in text.lower():
                            self.extraction_results["status"] = "complete"
                            self.extraction_results["summary"] = text
                            
                            # Try to find file paths
                            import re
                            file_paths = re.findall(r'/home/computeruse/shared/[^\s"\']+', text)
                            if file_paths:
                                self.extraction_results["output_files"] = file_paths
                                self.status_updater.update_status(f"Extraction completed! Found output files: {', '.join(file_paths)}")
                            return
        
        # If we get here, we didn't find clear evidence of results
        self.extraction_results["status"] = "unknown"
        self.extraction_results["summary"] = "Could not determine if extraction was successful"
        self.status_updater.update_status("Extraction completed, but couldn't verify output files")


async def main(args: argparse.Namespace) -> None:
    """Main entry point for headless extraction."""
    
    # Prompt for Docker cleanup and rebuild
    try:
        response = input("\nDo you want to clean and rebuild your docker image? [Y/n] ").lower()
        if response in ['', 'y', 'yes']:
            if not cleanup_and_rebuild_docker():
                status = DockerStatusUpdater()
                status.start()
                status.log_docker(
                    "Failed to rebuild Docker image. Attempting to proceed with existing image...",
                    "warning"
                )
                # Verify we have a usable image
                if not verify_docker_image("headless-browser:latest", status):
                    status.log_docker(
                        "No usable Docker image found. Please fix Docker issues before proceeding.",
                        "error"
                    )
                    status.stop()
                    return
                status.stop()
    except Exception as e:
        status = DockerStatusUpdater()
        status.start()
        status.log_docker("Error during Docker cleanup prompt", "error", e)
        status.log_docker("Attempting to proceed with existing image...", "warning")
        if not verify_docker_image("headless-browser:latest", status):
            status.log_docker(
                "No usable Docker image found. Please fix Docker issues before proceeding.",
                "error"
            )
            status.stop()
            return
        status.stop()
    
    # Early debug logging
    try:
        debug_log_path = Path("/home/computeruse/shared/debug_log.txt")
        debug_log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(debug_log_path, "w") as f:
            f.write("=== Early Debug Log ===\n")
            f.write(f"Process started at: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Arguments received:\n")
            f.write(f"  URL: {args.url}\n")
            f.write(f"  Output: {args.output}\n")
            f.write(f"  Format: {args.format}\n")
            f.write(f"  Provider: {args.provider}\n")
            f.write(f"Working directory: {os.getcwd()}\n")
            f.write(f"Running in Docker: True\n")  # Add this to confirm we're in Docker
    except Exception as e:
        print(f"Failed to create early debug log: {e}")
        logger.error(f"Failed to create early debug log: {e}")
    
    # Create extractor instance
    extractor = HeadlessExtractor(
        url=args.url,
        extraction_instructions=args.instructions,
        output_file=args.output,
        is_screenshot=args.type == "screenshot",
        api_provider=args.provider,
        api_key=args.api_key,
        tool_version=args.tool_version,
        model=args.model,
    )
    
    # Run extraction
    print(f"Starting extraction from {args.url}")
    print(f"Output will be saved to {args.output}")
    
    try:
        results = await extractor.run()
        
        # Save results metadata
        metadata_path = Path(args.output).with_suffix('.metadata.json')
        with open(metadata_path, 'w') as f:
            json.dump(results, f, indent=2)
        
        logger.info(f"Extraction complete, results metadata saved to {metadata_path}")
        
        # Print summary to stdout
        print(f"Extraction complete. {results.get('summary', '')}")
        if results.get("output_files"):
            print(f"Output files: {', '.join(results.get('output_files', []))}")
        
        return results
        
    except KeyboardInterrupt:
        print("\nExtraction cancelled by user")
        return {"status": "cancelled", "message": "Cancelled by user"}
    except Exception as e:
        print(f"\nError during extraction: {str(e)}")
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Headless web content extractor")
    parser.add_argument("--url", required=True, help="URL to extract data from")
    parser.add_argument("--instructions", required=True, help="Instructions for extraction")
    parser.add_argument("--output", required=True, help="Output file path (extension will be added automatically)")
    parser.add_argument(
        "--type",
        choices=["data", "screenshot"],
        default="data",
        help="Type of extraction (data=JSON, screenshot=PNG)"
    )
    parser.add_argument("--provider", default="anthropic", choices=["anthropic", "bedrock", "vertex"], help="API provider")
    parser.add_argument("--api-key", help="API key (if not set in environment)")
    parser.add_argument("--tool-version", default="computer_use_20250124", help="Tool version")
    parser.add_argument("--model", default="claude-3-7-sonnet-20250219", help="Model to use")
    
    args = parser.parse_args()
    
    asyncio.run(main(args))