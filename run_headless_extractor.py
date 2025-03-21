#!/usr/bin/env python3
"""
Run the Computer Use Demo container in headless mode for data extraction.
"""

import argparse
import os
import subprocess
from pathlib import Path
from typing import Optional
from headless_browser.extraction_cli import interactive_mode
from headless_browser.headless_extractor import cleanup_and_rebuild_docker, verify_docker_image, DockerStatusUpdater


def run_headless_extraction(
    url: str,
    instructions: str,
    output: str = "extraction_results.json",
    format: str = "json",
    api_provider: str = "anthropic",
    api_key: Optional[str] = None,
    model: str = "claude-3-7-sonnet-20250219",
    tool_version: str = "computer_use_20250124",
    shared_dir: Optional[str] = None,
):
    """
    Run headless extraction using the Computer Use Demo container.
    
    Args:
        url: URL to extract data from
        instructions: Instructions for Claude on what to extract
        output: Output filename (will be written to shared directory)
        format: Output format (json, csv, txt)
        api_provider: API provider (anthropic, bedrock, vertex)
        api_key: API key (defaults to ANTHROPIC_API_KEY env var)
        model: Model to use
        tool_version: Tool version to use
        shared_dir: Directory to mount as shared volume (defaults to ./shared)
    """
    # Determine user profile path
    user_home = str(Path.home())
    
    # Create shared directory if it doesn't exist
    if not shared_dir:
        shared_dir = Path("shared")
    else:
        shared_dir = Path(shared_dir)
    
    shared_dir.mkdir(exist_ok=True)
    shared_dir_abs = shared_dir.absolute()
    
    # Ensure the .anthropic directory exists
    anthropic_dir = Path(user_home) / ".anthropic"
    anthropic_dir.mkdir(exist_ok=True)
    
    # Get API key from environment if not provided
    if not api_key:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            try:
                from dotenv import load_dotenv
                load_dotenv()
                api_key = os.environ.get("ANTHROPIC_API_KEY")
            except ImportError:
                pass
    
    if not api_key and api_provider == "anthropic":
        print("Error: ANTHROPIC_API_KEY not found in environment variables or .env file")
        print("Please provide an API key with --api-key or set the ANTHROPIC_API_KEY environment variable")
        return 1
    
    # Build Docker command
    cmd = [
        "docker", "run",
        "--rm",  # Remove container after it exits
        "-e", f"HEADLESS_MODE=true",
        "-e", f"EXTRACTION_URL={url}",
        "-e", f"EXTRACTION_INSTRUCTIONS={instructions}",
        "-e", f"EXTRACTION_OUTPUT=/home/computeruse/shared/{output}",
        "-e", f"EXTRACTION_FORMAT={format}",
        "-e", f"API_PROVIDER={api_provider}",
        "-e", f"MODEL={model}",
        "-e", f"TOOL_VERSION={tool_version}",
    ]
    
    # Add API key if using Anthropic API
    if api_provider == "anthropic" and api_key:
        cmd.extend(["-e", f"ANTHROPIC_API_KEY={api_key}"])
    
    # Add volume mounts
    cmd.extend([
        "-v", f"{user_home}/.anthropic:/home/computeruse/.anthropic",
        "-v", f"{shared_dir_abs}:/home/computeruse/shared",
    ])
    
    # Add port mappings (for debugging purposes)
    cmd.extend([
        "-p", "6080:6080",  # NoVNC port for debugging
    ])
    
    # Add image name
    cmd.append("ghcr.io/anthropics/anthropic-quickstarts:computer-use-demo-latest")
    
    # Print command for debugging (masking API key)
    debug_cmd = list(cmd)
    for i, arg in enumerate(debug_cmd):
        if arg.startswith("ANTHROPIC_API_KEY="):
            debug_cmd[i] = "ANTHROPIC_API_KEY=********"
    
    print("Running command:")
    print(" ".join(debug_cmd))
    print(f"Extraction results will be saved to: {shared_dir_abs}/{output}")
    
    # Execute the command
    try:
        subprocess.run(cmd, check=True)
        print(f"\nExtraction complete! Check {shared_dir_abs}/{output} for results.")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"\nError running extraction: {e}")
        return e.returncode


def main():
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
                    return 1
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
            return 1
        status.stop()

    # Launch interactive mode
    return interactive_mode()


if __name__ == "__main__":
    import sys
    sys.exit(main())