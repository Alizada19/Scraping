# Exxen Content Scraper

A robust web scraper designed to extract comprehensive content metadata from [Exxen.com](https://www.exxen.com/). Built with Python and Playwright, it handles various content categories including series, competitions, documentaries, programs, and kids' content.

## Features

- **Automated Metadata Extraction:** Collects titles, descriptions, years, cast, directors, and more.
- **Support for Multi-Season Series:** Navigates through seasons and episodes to gather detailed information.
- **Stealth Browsing:** Utilizes `playwright-stealth` to bypass bot detection.
- **Media Asset Management:** Captures main images and thumbnails.
- **Flexible Data Export:** Saves extracted data to a local `exxen_data.json` file for easy access and processing.
- **Dynamic Interaction:** Mimics human-like behavior with random mouse movements and scrolls to ensure content loads correctly.

## Prerequisites

Before running the scraper, ensure you have the following installed:
- Python 3.8+
- [Playwright](https://playwright.dev/python/docs/intro)
- [PostgreSQL](https://www.postgresql.org/) (Optional, if using the database persistence feature)

## Installation

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd <repository-directory>
    ```

2.  **Install the required Python dependencies:**
    ```bash
    pip install playwright playwright-stealth psycopg2-binary python-dotenv pydantic
    ```

3.  **Install Playwright browsers:**
    ```bash
    playwright install chromium
    ```

## Configuration

The scraper uses environment variables for configuration. Create a `.env` file in the root directory and add the following:

```env
# Database Configuration (if applicable)
DB_NAME=your_db_name
DB_USER=your_db_user
DB_PASSWORD=your_db_password
DB_HOST=your_db_host
DB_PORT=your_db_port
```

*Note: The current version of `exxen.py` has the login and database saving logic commented out, focusing on local JSON output.*

## Usage

To start the scraping process, run the `exxen.py` script:

```bash
# In a terminal-only environment, use xvfb-run
xvfb-run python exxen.py
```

The script will launch a Chromium instance, navigate through the predefined categories, and output the collected data to `exxen_data.json`.

## Project Structure

- `exxen.py`: The main scraper script containing the logic for navigation and extraction.
- `exxen_data.json`: The default output file for the scraped metadata.
- `.env`: (User-provided) Configuration file for environment variables.
- `exxen_images/`: (Auto-generated) Directory for storing downloaded images.

## Disclaimer

This project is for educational and research purposes only. Please ensure you comply with Exxen's terms of service and legal requirements regarding web scraping.
