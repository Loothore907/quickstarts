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
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from anthropic import (
    Anthropic,
    AnthropicBedrock,
    AnthropicVertex,
)
from anthropic.types.beta import BetaMessageParam, BetaContentBlockParam

from computer_use_demo.loop import (
    APIProvider,
    SYSTEM_PROMPT,
    sampling_loop,
)
from computer_use_demo.tools import (
    TOOL_GROUPS_BY_VERSION,
    ToolResult,
    ToolVersion,
)

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

# Output directory for extracted data
OUTPUT_DIR = Path("/home/computeruse/shared")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

class StatusUpdater:
    """Updates status file in shared directory to provide feedback."""
    
    def __init__(self):
        self.status_file = Path("/home/computeruse/shared/container_status.txt")
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
            
    def update_status(self, status, increment_step=True):
        """Update the current status."""
        with self.lock:
            self.current_status = status
            if increment_step:
                self.steps_completed += 1
            self._write_status(status)
            
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


class HeadlessExtractor:
    """
    Headless extractor that uses Claude to extract data from websites without UI.
    """

    def __init__(
        self,
        url: str,
        extraction_instructions: str,
        output_file: str,
        output_format: str = "json",
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
            output_format: Format of the output data (json, csv, txt)
            api_provider: API provider to use (anthropic, bedrock, vertex)
            api_key: API key for the provider
            tool_version: Version of the tools to use
            model: Model to use for extraction
        """
        self.url = url
        self.extraction_instructions = extraction_instructions
        self.output_file = Path(output_file)
        self.output_format = output_format
        self.api_provider = APIProvider(api_provider)
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.tool_version = tool_version
        self.model = model
        
        # Messages for the conversation
        self.messages: List[BetaMessageParam] = []
        
        # Results of the extraction
        self.extraction_results: Dict[str, Any] = {}
        
        # Tool outputs captured during execution
        self.tool_outputs: Dict[str, ToolResult] = {}
        
        # Status updater
        self.status_updater = StatusUpdater()
        
        # Custom system prompt for extraction
        self.system_prompt_suffix = self._generate_system_prompt_suffix()

    def _generate_system_prompt_suffix(self) -> str:
        """Generate a specialized system prompt suffix for headless extraction."""
        return f"""
<EXTRACTION_TASK>
You are operating in headless mode to extract data from a website without human intervention.
Target URL: {self.url}
Extraction Instructions: {self.extraction_instructions}
Output Format: {self.output_format}

Please follow these steps:
1. Navigate to the provided URL
2. Identify and extract the requested information
3. Format the data as {self.output_format}
4. Save the extracted data to the shared directory

When you're finished, explicitly state that extraction is complete and summarize what was saved.
</EXTRACTION_TASK>

<IMPORTANT>
- You are operating without human oversight, so be thorough and careful
- Take screenshots at key points during the extraction process
- If you encounter any obstacles, try alternative approaches before giving up
- Format the final data properly according to the requested output format
- Save the data to a file in /home/computeruse/shared/ with a descriptive filename
</IMPORTANT>
"""

    async def _output_callback(self, content_block: BetaContentBlockParam) -> None:
        """Callback for capturing Claude's outputs."""
        if isinstance(content_block, dict) and content_block.get("type") == "text":
            text = content_block.get("text", "")
            logger.info(f"CLAUDE: {text[:100]}...")
            
            # Update status based on Claude's output
            lower_text = text.lower()
            if "navigating to" in lower_text or "opening" in lower_text:
                self.status_updater.update_status("Navigating to website...")
            elif "extracting" in lower_text or "gathering" in lower_text:
                self.status_updater.update_status("Extracting data from website...")
            elif "formatting" in lower_text or "organizing" in lower_text:
                self.status_updater.update_status("Formatting extracted data...")
            elif "saving" in lower_text or "writing" in lower_text:
                self.status_updater.update_status("Saving data to file...")
            elif "completed" in lower_text or "finished" in lower_text:
                self.status_updater.update_status("Extraction completed successfully!")
                
        elif isinstance(content_block, dict) and content_block.get("type") == "tool_use":
            tool_name = content_block.get("name", "")
            action = content_block.get("input", {}).get("action", "")
            logger.info(f"TOOL USE: {tool_name} - {action}")
            
            # Update status based on tool use
            if tool_name == "computer" and action == "screenshot":
                self.status_updater.update_status("Taking screenshot of current page...", increment_step=False)
            elif tool_name == "bash":
                self.status_updater.update_status("Executing command in bash...", increment_step=False)
            elif tool_name == "str_replace_editor":
                self.status_updater.update_status("Editing or saving file...", increment_step=False)

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
            self.status_updater.update_status(f"API error: {str(error)[:50]}...", increment_step=False)
        else:
            logger.info("API request successful")

    async def run(self) -> Dict[str, Any]:
        """Run the headless extraction process."""
        logger.info(f"Starting headless extraction of {self.url}")
        self.status_updater.start()
        
        try:
            # Initialize messages with the extraction task
            self.status_updater.update_status("Preparing extraction task...")
            self.messages = [
                {
                    "role": "user",
                    "content": f"Please extract data from {self.url} following these instructions: {self.extraction_instructions}. Save the results in {self.output_format} format to the shared directory."
                }
            ]
            
            # Run the sampling loop
            self.status_updater.update_status("Starting Claude extraction process...")
            self.messages = await sampling_loop(
                model=self.model,
                provider=self.api_provider,
                system_prompt_suffix=self.system_prompt_suffix,
                messages=self.messages,
                output_callback=self._output_callback,
                tool_output_callback=self._tool_output_callback,
                api_response_callback=self._api_response_callback,
                api_key=self.api_key,
                tool_version=self.tool_version,
                max_tokens=4096,
                thinking_budget=2048 if "3-7" in self.model else None,
                only_n_most_recent_images=3,
            )
            
            self.status_updater.update_status("Extraction process completed!")
            logger.info("Extraction process completed")
            
            # Look for results in the final messages
            self.status_updater.update_status("Analyzing extraction results...")
            self._parse_extraction_results()
            
            return self.extraction_results
            
        except Exception as e:
            error_msg = f"Error during extraction: {e}"
            logger.error(error_msg)
            self.status_updater.update_status(f"Error: {error_msg}")
            raise
        finally:
            self.status_updater.stop()

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
    # Create extractor instance
    extractor = HeadlessExtractor(
        url=args.url,
        extraction_instructions=args.instructions,
        output_file=args.output,
        output_format=args.format,
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
    parser = argparse.ArgumentParser(description="Headless web data extractor using Claude")
    parser.add_argument("--url", required=True, help="URL to extract data from")
    parser.add_argument("--instructions", required=True, help="Extraction instructions for Claude")
    parser.add_argument("--output", required=True, help="Output file path")
    parser.add_argument("--format", default="json", choices=["json", "csv", "txt"], help="Output format")
    parser.add_argument("--provider", default="anthropic", choices=["anthropic", "bedrock", "vertex"], help="API provider")
    parser.add_argument("--api-key", help="API key (if not set in environment)")
    parser.add_argument("--tool-version", default="computer_use_20250124", help="Tool version")
    parser.add_argument("--model", default="claude-3-7-sonnet-20250219", help="Model to use")
    
    args = parser.parse_args()
    
    asyncio.run(main(args))