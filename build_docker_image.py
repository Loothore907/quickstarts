#!/usr/bin/env python3
"""
Docker image builder for headless extraction.
This script builds the Docker image required for headless extraction.
"""

import subprocess
import os
import sys
import time
from pathlib import Path
import platform

def check_docker_installed():
    """Check if Docker is installed and running."""
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
    """Build the Docker image for headless extraction."""
    print("\n=== Building Docker Image for Headless Extraction ===\n")
    
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
    
    print("\n1. Building from local Dockerfile...")
    
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
        print("\nBuild output:")
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
    """Pull the image from GitHub container registry as a fallback."""
    print("\n2. Trying to pull image from GitHub Container Registry...")
    
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
    """Main function."""
    print("\n🐳 Docker Image Builder for Headless Extraction\n")
    
    # Create shared directory
    shared_dir = Path("./shared")
    shared_dir.mkdir(exist_ok=True)
    print(f"✅ Ensured shared directory exists at {shared_dir.absolute()}")
    
    # Build or pull the image
    success = build_image()
    
    if success:
        print("\n✅ Docker image 'headless-browser:latest' is ready to use")
        print("\nYou can now run the extraction tool:")
        print("    python extraction_cli.py")
        return 0
    else:
        print("\n❌ Failed to prepare Docker image")
        print("Please check Docker installation and try again")
        return 1

if __name__ == "__main__":
    sys.exit(main())