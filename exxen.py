import asyncio
import json
import logging
import os
import random
import uuid
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import psycopg2
from dotenv import load_dotenv
from playwright.async_api import async_playwright, Page, BrowserContext, Browser, TimeoutError
from playwright_stealth import Stealth

# Load environment variables
load_dotenv()

# Professional logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scraper.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("ExxenScraper")

class Storage:
    """Handles data persistence to PostgreSQL or JSON fallback."""
    def __init__(self):
        self.db_config = {
            "host": os.getenv("DB_HOST", "localhost"),
            "database": os.getenv("DB_NAME", "myScraperDatabase"),
            "user": os.getenv("DB_USER", "scraper_user"),
            "password": os.getenv("DB_PASS", "pass123*"),
            "port": os.getenv("DB_PORT", "5432")
        }
        self.use_db = True
        self.results = []
        try:
            conn = self._get_connection()
            conn.close()
            logger.info("Connected to PostgreSQL successfully.")
        except Exception as e:
            logger.warning(f"Could not connect to PostgreSQL: {e}. Falling back to JSON storage.")
            self.use_db = False
            if os.path.exists("results.json"):
                try:
                    with open("results.json", "r", encoding="utf-8") as f:
                        self.results = json.load(f)
                except Exception:
                    self.results = []

    def _get_connection(self):
        return psycopg2.connect(**self.db_config)

    def save_category(self, category_name: str) -> int:
        if not self.use_db:
            return random.randint(1000, 9999)

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    query = """
                    INSERT INTO categories (category_name)
                    VALUES (%s)
                    ON CONFLICT (category_name) DO NOTHING
                    RETURNING id;
                    """
                    cur.execute(query, (category_name,))
                    result = cur.fetchone()
                    if result:
                        category_id = result[0]
                    else:
                        cur.execute("SELECT id FROM categories WHERE category_name = %s", (category_name,))
                        category_id = cur.fetchone()[0]
                    conn.commit()
                    return category_id
        except Exception as e:
            logger.error(f"Error saving category {category_name}: {e}")
            return -1

    def save_item(self, category_id: int, title: str, details: Dict[str, Any]) -> bool:
        if not self.use_db:
            if any(r["title"] == title and r["category_id"] == category_id for r in self.results):
                return False
            
            self.results.append({
                "category_id": category_id,
                "title": title,
                "details": details
            })
            with open("results.json", "w", encoding="utf-8") as f:
                json.dump(self.results, f, indent=4, ensure_ascii=False)
            return True

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    json_data = json.dumps(details)
                    query = """
                        INSERT INTO items (category_id, title, details)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (category_id, title)
                        DO NOTHING;
                    """
                    cur.execute(query, (category_id, title, json_data))
                    inserted = cur.rowcount > 0
                    conn.commit()
                    return inserted
        except Exception as e:
            logger.error(f"Error saving item {title}: {e}")
            return False

class ExxenScraper:
    """Main scraper class for Exxen website."""
    def __init__(self, storage: Storage):
        self.storage = storage
        self.base_url = "https://www.exxen.com/"
        self.images_dir = "hotel_images"
        os.makedirs(self.images_dir, exist_ok=True)
        os.makedirs("categories", exist_ok=True)

    async def run(self, limit_categories: Optional[int] = None):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ])
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            stealth = Stealth()
            await stealth.apply_stealth_async(page)

            try:
                logger.info(f"Navigating to {self.base_url}")
                await page.goto(self.base_url, wait_until="networkidle")
                
                await self.handle_cookies(page)
                await self.scroll_page(page)
                
                sections = [
                    ('//*[@id="main-app"]/div[2]/main/div/div[4]/div/div[1]/div', "Categories"),
                    ('//*[@id="main-app"]/div[2]/main/div/div[3]/div/div[1]/div', "Featured"),
                    ('//*[@id="main-app"]/div[2]/main/div/div[5]/div/div[1]', "Reality")
                ]

                for xpath, name in sections:
                    await self.scrape_section(page, xpath, name, limit=limit_categories)

            except Exception as e:
                logger.exception(f"An error occurred during scraping: {e}")
            finally:
                await browser.close()

    async def handle_cookies(self, page: Page):
        try:
            accept_btn = page.get_by_text("Accept necessary only", exact=True)
            if await accept_btn.is_visible(timeout=5000):
                await accept_btn.click()
                logger.info("Cookie popup accepted")
        except Exception:
            logger.debug("Cookie popup not found or could not be clicked")

    async def scroll_page(self, page: Page):
        logger.info("Scrolling page to load content")
        await page.evaluate("""
            async () => {
                const step = 400;
                while (window.scrollY + window.innerHeight < document.body.scrollHeight) {
                    window.scrollBy(0, step);
                    await new Promise(r => setTimeout(r, 150));
                }
            }
        """)
        await asyncio.sleep(2)

    async def scrape_section(self, page: Page, section_xpath: str, section_name: str, limit: Optional[int] = None):
        logger.info(f"Processing section: {section_name}")
        container = page.locator(f'xpath={section_xpath}')
        try:
            await container.wait_for(state="attached", timeout=15000)
        except Exception:
            logger.warning(f"Section {section_name} container not found")
            return

        items = container.locator('xpath=./div')
        count = await items.count()
        logger.info(f"Found {count} items in {section_name}")

        to_process = min(count, limit) if limit else count
        for i in range(to_process):
            try:
                # Re-locate container and items to avoid stale elements after navigation
                container = page.locator(f'xpath={section_xpath}')
                item = container.locator('xpath=./div').nth(i)
                await item.wait_for(state="attached", timeout=5000)

                # Check for image and download it before clicking
                await self.download_image(page, item, f"section_{section_name}_{i}")

                await item.click()
                await page.wait_for_load_state("networkidle")

                category_title_locator = page.locator('xpath=//*[@id="main-app"]/div[2]/div[2]/main/div[2]/div/div')
                if await category_title_locator.count() > 0:
                    title = await category_title_locator.inner_text()
                    logger.info(f"Entered category: {title}")
                    category_id = self.storage.save_category(title)
                    
                    sub_item_xpath = '//*[@id="main-app"]/div[2]/div[2]/main/div[3]/div/div/div/div'
                    if "Featured" in section_name or "Reality" in section_name:
                         sub_item_xpath = '//*[@id="main-app"]/div[2]/div[2]/main/div[2]/div/div/div/div'

                    await self.scrape_category_items(page, sub_item_xpath, category_id)
                else:
                    logger.info("Direct item page detected")
                    category_id = self.storage.save_category(section_name)
                    await self.scrape_item_details(page, category_id)

                await page.goto(self.base_url, wait_until="networkidle")
                await self.scroll_page(page)
                container = page.locator(f'xpath={section_xpath}')
                await container.wait_for(state="attached", timeout=15000)

            except Exception as e:
                logger.error(f"Error processing item {i} in {section_name}: {e}")
                continue

    async def scrape_category_items(self, page: Page, sub_item_xpath: str, category_id: int):
        sub_items = page.locator(f'xpath={sub_item_xpath}')
        try:
            await sub_items.first.wait_for(state="attached", timeout=10000)
        except Exception:
            logger.warning("No sub-items found in category")
            return

        count = await sub_items.count()
        logger.info(f"Found {count} sub-items in category")

        for j in range(count):
            try:
                sub_items = page.locator(f'xpath={sub_item_xpath}')
                sub_item = sub_items.nth(j)
                await sub_item.wait_for(state="attached", timeout=5000)
                
                await self.download_image(page, sub_item, f"cat_{category_id}_item_{j}")

                await sub_item.click()
                await page.wait_for_load_state("networkidle")

                await self.scrape_item_details(page, category_id)

                await page.go_back()
                try:
                    await page.wait_for_selector(f'xpath={sub_item_xpath}', timeout=10000)
                except Exception:
                    # If go_back failed to restore list, maybe we need to navigate or wait more
                    logger.warning("Failed to restore sub-item list with go_back")
            except Exception as e:
                logger.error(f"Error scraping sub-item {j}: {e}")
                if page.url != self.base_url:
                     await page.go_back()
                continue

    async def scrape_item_details(self, page: Page, category_id: int):
        try:
            title_loc = page.locator('#main-app main p span').first
            title = await title_loc.inner_text(timeout=5000)
            
            # Use specific metadata container if possible, or filter spans
            metadata_loc = page.locator('#main-app main div div div div span')

            metadata = {}
            texts = []
            count = await metadata_loc.count()
            # Don't iterate all spans if there are too many, likely wrong selector
            max_spans = min(count, 10)
            for i in range(max_spans):
                t = await metadata_loc.nth(i).inner_text(timeout=2000)
                if t.strip():
                    texts.append(t.strip())

            metadata["year"] = "N/A"
            metadata["category"] = "N/A"
            metadata["part"] = "N/A"

            # Refined parsing: looking for Year (4 digits), Category, and Part (e.g. "X Seasons")
            for t in texts:
                if len(t) == 4 and t.isdigit():
                    metadata["year"] = t
                elif "Season" in t or "Part" in t:
                    metadata["part"] = t
                elif t not in ["•", "|", "/"] and metadata["category"] == "N/A":
                    # Avoid title if it leaked into texts
                    if t != title:
                        metadata["category"] = t

            desc_loc = page.locator('#main-app main div[class*="Spacing/md"] p')
            if await desc_loc.count() == 0:
                 desc_loc = page.locator('xpath=//*[@id="main-app"]/div[2]/main/div[2]/p')

            paragraphs = await desc_loc.all_inner_texts()
            # Filter out short or navigation-like text
            clean_paragraphs = [p.strip() for p in paragraphs if len(p.strip()) > 20]
            metadata["description"] = clean_paragraphs

            logger.info(f"Scraped item: {title}")
            self.storage.save_item(category_id, title, metadata)

        except Exception as e:
            logger.error(f"Failed to scrape item details: {e}")

    async def download_image(self, page: Page, container_locator, filename_prefix: str, retries: int = 3):
        """Resilient image download with retries and backoff."""
        try:
            img = container_locator.locator("img").first
            if not await img.is_visible(timeout=2000):
                return

            src = await img.get_attribute("srcset")
            if src:
                src = src.split(",")[-1].split(" ")[0]

            if not src:
                src = await img.get_attribute("data-src")
            if not src:
                src = await img.get_attribute("src")

            if not src:
                return

            full_url = urljoin(page.url, src)

            for attempt in range(retries):
                try:
                    response = await page.context.request.get(full_url, timeout=10000)
                    if response.ok:
                        content = await response.body()
                        ext = os.path.splitext(urlparse(full_url).path)[1].split('?')[0] or ".jpg"
                        if not ext.startswith('.'): ext = ".jpg"

                        filename = f"{filename_prefix}_{uuid.uuid4().hex[:8]}{ext}"

                        for folder in [self.images_dir, "categories"]:
                            path = os.path.join(folder, filename)
                            with open(path, "wb") as f:
                                f.write(content)
                        logger.debug(f"Downloaded image: {filename}")
                        return
                    else:
                        logger.warning(f"Failed to download image (attempt {attempt+1}): {response.status}")
                except Exception as e:
                    logger.warning(f"Download error (attempt {attempt+1}): {e}")

                await asyncio.sleep(2 ** attempt) # Exponential backoff
                
        except Exception as e:
            logger.debug(f"Image extraction failed: {e}")

import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Exxen Web Scraper")
    parser.add_argument("--limit", type=int, default=None, help="Limit the number of categories to scrape")
    args = parser.parse_args()

    storage = Storage()
    scraper = ExxenScraper(storage)
    asyncio.run(scraper.run(limit_categories=args.limit))
