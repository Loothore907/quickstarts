# Headless Mode Quickstart Guide

This guide explains how to set up and use the Computer Use Demo in headless mode for automated data extraction.

## Setup Instructions

### 1. Add New Files

Add this new file to your project:

| File | Path | Purpose |
|------|------|---------|
| `status_updater.py` | `computer_use_demo/status_updater.py` | Helper utility for status updates |

### 2. Modify Existing Files

Update these existing files with the improved functionality:

| File | Path | Purpose |
|------|------|---------|
| `headless_extractor.py` | `computer_use_demo/headless_extractor.py` | Core extraction module with status updates |
| `extraction_cli.py` | Project root directory | CLI with progress feedback |
| `entrypoint.sh` | `image/entrypoint.sh` | Container entry point with headless support |

### 3. Prepare Environment

```
# Create shared directory for extraction results
mkdir shared

# Copy environment template (if using .env file)
copy .env.sample .env
# Edit .env with your settings using your preferred text editor
```

## Running Headless Extractions

### Method 1: Using the Interactive CLI

This method provides a guided interface with real-time progress feedback:

```
python extraction_cli.py
```

Follow the prompts to enter:
- URL to extract data from
- Extraction instructions
- Output filename and format

You'll see real-time progress updates during extraction:
```
[45s] Navigating to website... (20% complete)
[112s] Extracting data from website... (60% complete) 
[189s] Extraction completed successfully! (100% complete)
```

### Method 2: Using CLI Arguments

For automation or scripting:

```
python extraction_cli.py --url "cannagethappyak.com" --instructions "Extract all product names and prices" --output "cannagethappyak_com_data_20250320.json"
```

### Method 3: Using Docker Directly

For lower-level control:

```
docker run --rm ^
  -e HEADLESS_MODE=true ^
  -e ANTHROPIC_API_KEY="your_api_key" ^
  -e EXTRACTION_URL="cannagethappyak.com" ^
  -e EXTRACTION_INSTRUCTIONS="Extract all product names and prices" ^
  -e EXTRACTION_OUTPUT="/home/computeruse/shared/cannagethappyak_com_data_20250320.json" ^
  -e EXTRACTION_FORMAT="json" ^
  -v "%CD%\shared:/home/computeruse/shared" ^
  -v "%USERPROFILE%\.anthropic:/home/computeruse/.anthropic" ^
  ghcr.io/anthropics/anthropic-quickstarts:computer-use-demo-latest
```

### Method 4: Using Docker Compose

Edit variables in `.env` file, then run:

```
docker-compose up headless
```

## New Progress Feedback Features

### Real-time Status Updates

The extraction process now provides continuous feedback through:

1. **Live Progress Display**: Shows current extraction stage and estimated completion percentage
2. **Elapsed Time Tracking**: Shows how long the extraction has been running
3. **Activity Indicators**: Spinners or progress animations to show the system is working

### Status Files

The system creates two status files you can monitor:

1. **extraction_status.txt**: Created in the shared directory, shows high-level status
2. **container_status.txt**: More detailed status from inside the container

These files are updated every few seconds and can be monitored by other applications.

### Monitoring Options

Several ways to monitor extraction progress:

1. **Console Output**: Real-time updates in the console
2. **Status Files**: Check status files in the shared directory
3. **NoVNC Interface**: Watch the desktop during extraction at http://localhost:6080/vnc.html

### Error Handling Improvements

The system now handles errors more gracefully:

1. **Unicode Support**: Properly handles special characters in output
2. **Keyboard Interruption**: Ctrl+C now cleanly stops the extraction
3. **Detailed Error Reporting**: More informative error messages 

## Integration with Existing Systems

### Triggering from Failed Scraping Jobs

Add this code to your scraping workflow to fallback to headless extraction:

```python
def scrape_website(url):
    try:
        # Your existing scraping code
        result = regular_scraper.scrape(url)
        return result
    except ScrapingFailedException:
        # Fallback to headless extraction
        import subprocess
        extraction_instructions = "Extract all product information including name, price, and description"
        subprocess.run([
            "python", "extraction_cli.py",
            "--url", url,
            "--instructions", extraction_instructions,
            "--output", f"{url.replace('https://', '').replace('http://', '').split('/')[0].replace('.', '_')}_data_{datetime.now().strftime('%Y%m%d')}.json"
        ])
        
        # Process the results
        with open(f"shared/{url.replace('https://', '').replace('http://', '').split('/')[0].replace('.', '_')}_data_{datetime.now().strftime('%Y%m%d')}.json", "r") as f:
            return json.load(f)
```

### Admin Dashboard Integration

For your admin dashboard:

1. **Status Monitoring**: Poll the status files to display progress
2. **Extraction Triggering**: Start extractions via the CLI
3. **Results Display**: Show extraction results in your dashboard

## Customizing Extraction Instructions

For best results, provide clear and specific extraction instructions. The extraction system uses Claude to navigate websites and extract data, so you can write naturally detailed instructions:

### Example: Product Extraction

```
Extract all products from this e-commerce page. For each product include:
1. Product name
2. Price (numeric value only)
3. Currency symbol
4. Short description
5. Available sizes or options

Format the data as a JSON array of objects, with each object having the fields: name, price, currency, description, and options.
```

### Example: Cannabis Dispensary Menu

```
Extract the complete menu from this dispensary website. For each product include:
1. Product name
2. Category/Type (e.g., Flower, Concentrate, Edible)
3. Brand or producer name
4. THC percentage/content
5. CBD percentage/content (if available)
6. Price
7. Size/weight
8. Strain type (Indica, Sativa, Hybrid)

Format the data as a JSON array of objects with appropriate fields for each product.
```

### Example: Table Extraction

```
Find the data table on this page and extract all rows and columns.
Each row should have the following fields matching the table headers:
- Quarter
- Revenue
- Profit
- Growth Rate

Format the data as CSV with headers.
```

## Troubleshooting

### Common Issues

1. **No Progress Updates**: If you don't see progress updates, check that the status files are being created in the shared directory

2. **Extraction Takes Too Long**: Try simplifying instructions or extracting from smaller pages

3. **No Output File**: Check the container logs and/or metadata file for error information

4. **Poor Quality Results**: Refine your extraction instructions to be more specific

### Debugging

1. View the virtual desktop during extraction by opening http://localhost:6080/vnc.html

2. Check extraction logs in `extraction.log`

3. Inspect metadata file (same name as output with `.metadata.json` extension)

4. Monitor the status files in the shared directory for real-time updates