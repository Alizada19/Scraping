# Exxen Scraper Project

A robust web scraping application is made by Ali Alizada for extracting movie and series categories, details, and metadata from [Exxen.com](https://www.exxen.com/). The scraper uses Playwright with stealth mechanisms to bypass bot detection and supports data persistence via PostgreSQL.

## Features

- **Stealth Browsing**: Integrates `playwright-stealth` to emulate real user behavior and avoid detection.
- **Categorized Data Extraction**: Automatically discovers and scrapes content from featured, reality, and other custom categories.
- **Automated Media Assets**: Downloads high-resolution thumbnails and images directly to a local directory.
- **Data Persistence**: Designed to store scraped information (titles, descriptions, years, etc.) into a PostgreSQL database.
- **Error Handling**: Implements retry logic and graceful failure for individual scraping items to ensure overall process completion.

## Requirements

The project uses Python 3 and the following primary dependencies:
- [Playwright](https://playwright.dev/python/) for browser automation.
- `playwright-stealth` for evasion techniques.
- `psycopg2-binary` for PostgreSQL database interaction.
- `pydantic` for data validation.
- `python-dotenv` for environment variable management.

## Installation

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd <repository-directory>
    ```

2.  **Install Python dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Install Playwright browser binaries:**
    ```bash
    playwright install chromium
    ```

4.  **Database Setup**:
    Ensure you have a PostgreSQL server running and create the necessary tables (`categories` and `items`). You can use the configuration details found in `exxen.py` or customize them via environment variables.

## Usage

To run the scraper:

```bash
python exxen.py
```

*Note: Since the script is configured with `headless=False`, ensure you are running it in an environment with a display (or use `xvfb-run` for headless server environments).*

## Project Structure

- `exxen.py`: The main scraper script containing the scraping logic and database connection functions.
- `requirements.txt`: Lists all Python dependencies.
- `images/`: (Created at runtime) Directory where downloaded images are stored.

## Configuration

The script uses hardcoded database credentials by default. It is recommended to migrate these to a `.env` file for production environments.

---

*Disclaimer: This project is for educational purposes only. Ensure compliance with the website's Terms of Service and robots.txt before scraping.*
