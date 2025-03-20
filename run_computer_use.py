#!/usr/bin/env python3
import os
import subprocess
import sys
import platform
from pathlib import Path

def setup_environment():
    """Set up virtual environment and install dependencies."""
    # Create .venv directory if it doesn't exist
    if not Path('.venv').exists():
        print("Creating virtual environment...")
        subprocess.run([sys.executable, "-m", "venv", ".venv"], check=True)

    # Determine activation script based on platform
    if platform.system() == "Windows":
        activate_script = ".venv\\Scripts\\activate"
        activate_cmd = f"call {activate_script}"
    else:
        activate_script = ".venv/bin/activate"
        activate_cmd = f"source {activate_script}"

    # Add python-dotenv to dev-requirements.txt if not already there
    dev_req_path = Path("dev-requirements.txt")
    if dev_req_path.exists():
        content = dev_req_path.read_text()
        if "python-dotenv" not in content:
            with open(dev_req_path, "a") as f:
                f.write("\npython-dotenv>=1.0.0\n")
    
    # Install requirements
    print("Installing requirements...")
    if platform.system() == "Windows":
        install_cmd = f"{activate_cmd} && pip install -r dev-requirements.txt"
        subprocess.run(install_cmd, shell=True, check=True)
    else:
        subprocess.run(f"bash -c '{activate_cmd} && pip install -r dev-requirements.txt'", 
                       shell=True, check=True)
    
    print("Virtual environment setup complete!")

def run_docker():
    """Run the Docker container with environment variables."""
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
    
    # Ensure the .anthropic directory exists
    anthropic_dir = Path(user_home) / ".anthropic"
    anthropic_dir.mkdir(exist_ok=True)
    
    # Build Docker command
    cmd = [
        "docker", "run",
        "-e", f"ANTHROPIC_API_KEY={api_key}",
        "-v", f"{user_home}/.anthropic:/home/computeruse/.anthropic",
        "-p", "5900:5900",
        "-p", "8501:8501",
        "-p", "6080:6080", 
        "-p", "8080:8080",
        "-it", "ghcr.io/anthropics/anthropic-quickstarts:computer-use-demo-latest"
    ]
    
    # Execute the command
    print("Starting Computer Use Demo...")
    subprocess.run(cmd)

def main():
    """Main function to set up environment and run Docker container."""
    # Check if setup needed
    if not Path(".venv").exists() or "--setup" in sys.argv:
        setup_environment()
    
    # Run Docker container
    run_docker()

if __name__ == "__main__":
    main()