#!/usr/bin/env python3
import os
import subprocess
from pathlib import Path

def run_docker():
    """Run the Docker container with environment variables and shared volume."""
    # Import dotenv here after it's installed
    try:
        from dotenv import load_dotenv
    except ImportError:
        print("Error: python-dotenv not installed. Run setup again.")
        return

    # Load API key from .env file
    load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not found in .env file")
        # Create .env file template if it doesn't exist
        if not Path(".env").exists():
            with open(".env", "w") as f:
                f.write("ANTHROPIC_API_KEY=your_api_key_here\n")
            print("Created .env file template. Please edit it to add your API key.")
        return
    
    # Determine user profile path
    user_home = str(Path.home())
    
    # Create shared directory if it doesn't exist
    shared_dir = Path("shared")
    shared_dir.mkdir(exist_ok=True)
    
    # Ensure the .anthropic directory exists
    anthropic_dir = Path(user_home) / ".anthropic"
    anthropic_dir.mkdir(exist_ok=True)
    
    # Get absolute path to shared directory
    shared_dir_abs = shared_dir.absolute()
    
    # Build Docker command
    cmd = [
        "docker", "run",
        "-e", f"ANTHROPIC_API_KEY={api_key}",
        "-v", f"{user_home}/.anthropic:/home/computeruse/.anthropic",
        "-v", f"{shared_dir_abs}:/home/computeruse/shared",
        "-p", "5900:5900",
        "-p", "8501:8501",
        "-p", "6080:6080", 
        "-p", "8080:8080",
        "-it", "ghcr.io/anthropics/anthropic-quickstarts:computer-use-demo-latest"
    ]
    
    # Execute the command
    print("Starting Computer Use Demo...")
    print(f"Shared directory created at: {shared_dir_abs}")
    print("Inside the container, save files to: /home/computeruse/shared/")
    subprocess.run(cmd)

if __name__ == "__main__":
    run_docker() 