"""
Status updater module for providing feedback during headless extractions.
This module helps track and report progress during automated extractions.
"""

import os
import sys
import time
import shutil
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

class LogManager:
    """Manages log files with rotation and archiving capabilities."""
    
    def __init__(self, shared_dir: str = "/home/computeruse/shared"):
        self.shared_dir = Path(shared_dir)
        self.log_dir = self.shared_dir / "logs"
        self.archive_dir = self.log_dir / "archive"
        
        # Create necessary directories
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        
        # Define log files
        self.container_status_file = self.shared_dir / "container_status.txt"
        self.extraction_status_file = self.shared_dir / "extraction_status.txt"
        self.debug_log_file = self.shared_dir / "debug_log.txt"
        
        # Initialize archive tracking
        self.last_archive_check = time.time()
        self.archive_check_interval = 86400  # 24 hours
    
    def get_log_path(self, log_name: str, domain: Optional[str] = None) -> Path:
        """Get the path for a log file, optionally domain-specific."""
        if domain:
            domain_log_dir = self.log_dir / domain
            domain_log_dir.mkdir(parents=True, exist_ok=True)
            return domain_log_dir / f"{log_name}.log"
        return self.log_dir / f"{log_name}.log"
    
    def archive_logs(self, force: bool = False):
        """Archive logs older than 7 days or if forced."""
        current_time = time.time()
        
        # Only check periodically unless forced
        if not force and (current_time - self.last_archive_check) < self.archive_check_interval:
            return
            
        self.last_archive_check = current_time
        
        # Archive date-based directory name
        archive_date = datetime.now().strftime("%Y%m%d")
        date_archive_dir = self.archive_dir / archive_date
        date_archive_dir.mkdir(exist_ok=True)
        
        # Move status files if they exist and backup before overwriting
        for status_file in [self.container_status_file, self.extraction_status_file, self.debug_log_file]:
            if status_file.exists():
                # Create a backup with timestamp
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_name = f"{status_file.stem}_{timestamp}{status_file.suffix}"
                backup_path = date_archive_dir / backup_name
                
                try:
                    # Copy file to archive, don't remove original
                    shutil.copy2(status_file, backup_path)
                except Exception as e:
                    print(f"Error archiving {status_file}: {e}")
    
    def append_to_log(self, log_name: str, content: str, domain: Optional[str] = None):
        """Append content to a log file."""
        try:
            log_path = self.get_log_path(log_name, domain)
            
            # Ensure parent directory exists
            log_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(log_path, 'a', encoding='utf-8') as f:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"[{timestamp}] {content}\n")
        except Exception as e:
            print(f"Error writing to log {log_name} for domain {domain}: {e}")
            print(traceback.format_exc())
    
    def write_status(self, status: str, is_container: bool = True):
        """Write to status files with automatic archiving."""
        # Check if we should archive logs
        self.archive_logs()
        
        status_file = self.container_status_file if is_container else self.extraction_status_file
        
        try:
            # Ensure directory exists - use absolute paths
            status_file.parent.mkdir(exist_ok=True, parents=True)
            
            # Write status to file with explicit encoding
            with open(status_file, 'w', encoding='utf-8') as f:
                f.write(f"{status}\n")
                f.write(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                
            # Also append to historical log
            log_name = "container_log" if is_container else "extraction_log"
            self.append_to_log(log_name, status)
                
        except Exception as e:
            print(f"Error writing status to {status_file}: {e}")
            print(traceback.format_exc())
            
            # Try writing to an alternative location
            try:
                alt_file = self.shared_dir / "status_write_error.log"
                with open(alt_file, 'a', encoding='utf-8') as f:
                    f.write(f"[{datetime.now().isoformat()}] Error writing status: {e}\n")
                    f.write(f"  - Attempted to write to: {status_file}\n")
                    f.write(f"  - Status content: {status}\n")
                    f.write(f"  - Traceback: {traceback.format_exc()}\n")
            except:
                pass

class StatusUpdater:
    """
    Updates status files to provide feedback during extractions.
    Creates and maintains status files that can be monitored by
    external processes to track extraction progress.
    """
    
    def __init__(self, shared_dir: str = "/home/computeruse/shared", domain: Optional[str] = None):
        """
        Initialize the status updater.
        
        Args:
            shared_dir: Path to the shared directory where status files are written
            domain: Optional domain name for domain-specific logging
        """
        self.shared_dir = Path(shared_dir)
        self.domain = domain
        self.running = False
        self.current_status = "Initializing extraction process..."
        self.lock = threading.Lock()
        self.steps_completed = 0
        self.total_steps = 5  # Approximate number of steps in extraction
        self.start_time = time.time()
        self.has_problem = False
        self.last_update_time = time.time()
        self.status_file = self.shared_dir / "container_status.txt"
        
        # Initialize log manager
        self.log_manager = LogManager(shared_dir)
        
        # Create shared directory
        self.shared_dir.mkdir(exist_ok=True, parents=True)
        
    def start(self):
        """
        Start the status updater thread.
        Begins regular status file updates.
        """
        self.running = True
        self.start_time = time.time()
        self.last_update_time = time.time()
        
        # Create thread with exception handling
        self.thread = threading.Thread(target=self._update_loop_with_exception_handling, daemon=True)
        self.thread.start()
        
        # Write initial status immediately and log the start
        initial_status = "Container started successfully - beginning extraction setup"
        self._write_status(initial_status)
        
        try:
            self.log_manager.append_to_log(
                "extraction_events", 
                f"Started extraction process for domain: {self.domain or 'unknown'}", 
                self.domain
            )
        except Exception as e:
            print(f"Error logging start event: {e}")
        
    def _update_loop_with_exception_handling(self):
        """Wrapper for _update_loop with exception handling."""
        try:
            self._update_loop()
        except Exception as e:
            print(f"Error in status update loop: {e}")
            print(traceback.format_exc())
            
            # Try to write error to log
            try:
                with open(self.shared_dir / "update_loop_error.log", 'a') as f:
                    f.write(f"[{datetime.now().isoformat()}] Error in update loop: {e}\n")
                    f.write(f"Traceback: {traceback.format_exc()}\n")
            except:
                pass
        
    def stop(self):
        """
        Stop the status updater thread.
        Cleanly terminates the status update process.
        """
        self.running = False
        if hasattr(self, 'thread') and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        
        # Log the stop event
        if self.domain:
            try:
                self.log_manager.append_to_log(
                    "extraction_events",
                    f"Stopped extraction process for domain: {self.domain}",
                    self.domain
                )
            except Exception as e:
                print(f"Error logging stop event: {e}")
            
    def update_status(self, status: str, increment_step: bool = True, is_problem: bool = False):
        """
        Update the current status.
        
        Args:
            status: New status message
            increment_step: Whether to increment the step counter
            is_problem: Whether this status represents a problem
        """
        with self.lock:
            # Update timestamp
            self.last_update_time = time.time()
            
            # Format message with appropriate prefix
            if is_problem:
                self.has_problem = True
                formatted_status = f"I HAVE A PROBLEM: {status}"
            else:
                formatted_status = f"SUCCESSFULLY COMPLETED: {status}" if increment_step else f"PROGRESS UPDATE: {status}"
            
            self.current_status = formatted_status
            if increment_step:
                self.steps_completed += 1
            self._write_status(formatted_status)
            
    def has_error(self) -> bool:
        """
        Check if the current status indicates an error.
        
        Returns:
            True if there is an error, False otherwise
        """
        return self.has_problem
    
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
        inactivity_warning_interval = 60  # seconds
        inactivity_warning_shown = False
        
        while self.running:
            try:
                with self.lock:
                    elapsed = self.get_elapsed_time()
                    progress = min(100, int((self.steps_completed / self.total_steps) * 100))
                    
                    # Check for potential stalled process
                    time_since_update = time.time() - self.last_update_time
                    if time_since_update > inactivity_warning_interval and not inactivity_warning_shown:
                        print(f"\n⚠️ Warning: No status updates for {time_since_update:.0f} seconds, process may be stalled")
                        inactivity_warning_shown = True
                    elif time_since_update < inactivity_warning_interval:
                        inactivity_warning_shown = False
                    
                    status = f"{self.current_status} ({progress}% complete, {elapsed:.0f}s elapsed)"
                    self._write_status(status)
            except Exception as e:
                print(f"Error in update loop iteration: {e}")
                
            time.sleep(2)  # Update every 2 seconds
            
    def _write_status(self, status: str):
        """Write status to file and append to logs."""
        try:
            # First, verify shared directory exists
            self.shared_dir.mkdir(exist_ok=True, parents=True)
            
            # Ensure status file parent directory exists
            self.status_file.parent.mkdir(exist_ok=True, parents=True)
            
            # Try writing directly to status file as a fallback
            try:
                with open(self.status_file, 'w', encoding='utf-8') as f:
                    f.write(f"{status}\n")
                    f.write(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            except Exception as direct_write_error:
                print(f"Direct status file write failed: {direct_write_error}")
                # Continue to try the log manager method
            
            # Write to main status file through log manager
            try:
                self.log_manager.write_status(status, is_container=True)
            except Exception as log_manager_error:
                print(f"Log manager status write failed: {log_manager_error}")
                # We already tried direct write above, so just continue
            
            # Write domain-specific log if we have a domain
            if self.domain:
                try:
                    self.log_manager.append_to_log("extraction_log", status, self.domain)
                except Exception as e:
                    print(f"Error writing domain log: {e}")
            
            # Format output for console
            elapsed = self.get_elapsed_time()
            
            # Format the output with colors for terminal
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
            
        except Exception as e:
            # More robust error handling with backtrace
            print(f"ERROR WRITING STATUS: {e}")
            print(traceback.format_exc())
            
            # Try writing to alternative location
            try:
                error_log_path = self.shared_dir / "status_error.log"
                with open(error_log_path, 'a', encoding='utf-8') as f:
                    f.write(f"[{datetime.now().isoformat()}] Error writing status: {e}\n")
                    f.write(f"  - Attempted to write: {status}\n")
                    f.write(f"  - Traceback: {traceback.format_exc()}\n")
            except Exception as error_log_error:
                print(f"Failed to write error log: {error_log_error}")
