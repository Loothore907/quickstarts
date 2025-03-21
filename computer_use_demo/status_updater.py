"""
Status updater module for providing feedback during headless extractions.
This module helps track and report progress during automated extractions.
"""

import os
import time
import threading
from pathlib import Path
from typing import Optional

class StatusUpdater:
    """
    Updates status files to provide feedback during extractions.
    Creates and maintains status files that can be monitored by
    external processes to track extraction progress.
    """
    
    def __init__(self, shared_dir: str = "/home/computeruse/shared"):
        """
        Initialize the status updater.
        
        Args:
            shared_dir: Path to the shared directory where status files are written
        """
        self.shared_dir = Path(shared_dir)
        self.status_file = self.shared_dir / "container_status.txt"
        self.running = False
        self.current_status = "Initializing extraction process..."
        self.lock = threading.Lock()
        self.steps_completed = 0
        self.total_steps = 5  # Approximate number of steps in extraction
        self.start_time = time.time()
        
    def start(self):
        """
        Start the status updater thread.
        Begins regular status file updates.
        """
        self.running = True
        self.start_time = time.time()
        self.thread = threading.Thread(target=self._update_loop, daemon=True)
        self.thread.start()
        
    def stop(self):
        """
        Stop the status updater thread.
        Cleanly terminates the status update process.
        """
        self.running = False
        if hasattr(self, 'thread') and self.thread.is_alive():
            self.thread.join(timeout=1.0)
            
    def update_status(self, status: str, increment_step: bool = True):
        """
        Update the current status.
        
        Args:
            status: New status message
            increment_step: Whether to increment the step counter
        """
        with self.lock:
            self.current_status = status
            if increment_step:
                self.steps_completed += 1
            self._write_status(status)
            
    def get_elapsed_time(self) -> float:
        """
        Get elapsed time in seconds since the updater was started.
        
        Returns:
            Elapsed time in seconds
        """
        return time.time() - self.start_time
            
    def _update_loop(self):
        """
        Main update loop that writes status to file regularly.
        Runs in a separate thread and updates status files on a
        regular interval.
        """
        while self.running:
            with self.lock:
                elapsed = self.get_elapsed_time()
                progress = min(100, int((self.steps_completed / self.total_steps) * 100))
                status = f"{self.current_status} ({progress}% complete, {elapsed:.0f}s elapsed)"
                self._write_status(status)
            time.sleep(2)  # Update every 2 seconds
            
    def _write_status(self, status: str):
        """
        Write status to file.
        
        Args:
            status: Status message to write
        """
        try:
            # Ensure directory exists
            self.shared_dir.mkdir(parents=True, exist_ok=True)
            
            # Write status to file
            with open(self.status_file, 'w', encoding='utf-8') as f:
                f.write(f"{status}\n")
                f.write(f"Last updated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        except Exception as e:
            print(f"Error writing status: {e}")