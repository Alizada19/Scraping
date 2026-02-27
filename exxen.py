import asyncio
import json
import os
import random
import uuid
from urllib.parse import urljoin, urlparse
import psycopg2
from playwright.async_api import async_playwright, Page
from playwright_stealth import Stealth
from dotenv import load_dotenv

# Load environment variables from .env file (database host, user, pass, etc.)
load_dotenv()

# --- CONFIGURATION ---
BASE_URL = "https://www.exxen.com/"
MEDIA_DIR = "media_assets"
os.makedirs(MEDIA_DIR, exist_ok=True)

# --- DATABASE FUNCTIONS ---

def get_db_connection():
    """Returns a connection to the PostgreSQL database using environment variables."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        database=os.getenv("DB_NAME", "myScraperDatabase"),
        user=os.getenv("DB_USER", "scraper_user"),
        password=os.getenv("DB_PASS", "pass123*"),
        port=os.getenv("DB_PORT", "5432")
    )

def save_category(name):
    """Saves a category to the database and returns its unique ID."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # Insert if it doesn't exist, ignore otherwise
        cur.execute("""
            INSERT INTO categories (category_name)
            VALUES (%s)
            ON CONFLICT (category_name) DO NOTHING
            RETURNING id;
        """, (name,))
        result = cur.fetchone()

        # If it already existed, fetch its ID
        if not result:
            cur.execute("SELECT id FROM categories WHERE category_name = %s", (name,))
            result = cur.fetchone()

        category_id = result[0]
        conn.commit()
        cur.close()
        conn.close()
        return category_id
    except Exception as e:
        print(f"Database error (save_category): {e}. Falling back to random ID.")
        return random.randint(1000, 9999)

def save_item(category_id, data):
    """Saves item details to the database or appends to a local JSON file if DB fails."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # Insert the item and its JSON details
        cur.execute("""
            INSERT INTO items (category_id, title, details)
            VALUES (%s, %s, %s)
            ON CONFLICT (category_id, title) DO NOTHING;
        """, (category_id, data["title"], json.dumps(data["details"])))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Database error (save_item): {e}. Saving data to results.json instead.")
        results = []
        if os.path.exists("results.json"):
            try:
                with open("results.json", "r", encoding="utf-8") as f:
                    results = json.load(f)
            except: pass

        results.append({"category_id": category_id, **data})
        with open("results.json", "w", encoding="utf-8") as f:
            json.dump(results, f, indent=4, ensure_ascii=False)

# --- SCRAPING FUNCTIONS ---

async def scroll_page(page: Page):
    """Slowly scrolls down the page to ensure all dynamic content and lazy images are loaded."""
    await page.evaluate("""
        async () => {
            // Scroll down in steps to trigger lazy loading
            for (let i = 0; i < 8; i++) {
                window.scrollBy(0, 600);
                await new Promise(r => setTimeout(r, 250));
            }
        }
    """)

async def download_media(page: Page, locator, prefix):
    """Identifies and downloads the highest resolution image found in the given locator."""
    try:
        img = locator.locator("img").first
        if not await img.is_visible(): return None

        # Check srcset (best), then data-src, then regular src
        src = await img.get_attribute("srcset")
        if src: src = src.split(",")[-1].split(" ")[0]
        if not src: src = await img.get_attribute("data-src")
        if not src: src = await img.get_attribute("src")

        if not src: return None

        # Form full URL and download the file
        url = urljoin(page.url, src)
        response = await page.context.request.get(url)
        if response.ok:
            # Clean extension from URL query params
            ext = os.path.splitext(urlparse(url).path)[1].split('?')[0] or ".jpg"
            filename = f"{prefix}_{uuid.uuid4().hex[:8]}{ext}"

            filepath = os.path.join(MEDIA_DIR, filename)
            with open(filepath, "wb") as f:
                f.write(await response.body())
            return filepath
    except Exception as e:
        print(f"Media download failed for {prefix}: {e}")
    return None

async def scrape_item_details(page: Page, category_id, item_image_path=None):
    """Extracts text metadata (year, category, part) and description from a content page."""
    try:
        # Extract title from the specific header location
        title = await page.locator('#main-app main p span').first.inner_text(timeout=5000)

        # Extract metadata spans (Year, Genre, Season Info)
        meta_loc = page.locator('#main-app main div div div div span')
        # Filter only non-empty strings
        texts = [t.strip() for t in await meta_loc.all_inner_texts() if t.strip()]

        details = {
            "year": "N/A",
            "category": "N/A",
            "part": "N/A",
            "description": [],
            "image_path": item_image_path
        }
        for t in texts:
            if t.isdigit() and len(t) == 4:
                details["year"] = t
            elif "Season" in t or "Part" in t:
                details["part"] = t
            elif t not in ["•", "|", "/"] and t != title:
                # If it's not a separator or the title, it's likely the category
                if details["category"] == "N/A": details["category"] = t

        # Extract multi-paragraph description
        # Targets the div containing description paragraphs
        desc_loc = page.locator('#main-app main div[class*="Spacing/md"] p')
        if await desc_loc.count() == 0:
            # Fallback to the original XPath if CSS fails
            desc_loc = page.locator('xpath=//*[@id="main-app"]/div[2]/main/div[2]/p')

        # Filter for meaningful paragraphs (longer than 20 chars)
        details["description"] = [p.strip() for p in await desc_loc.all_inner_texts() if len(p.strip()) > 20]

        print(f"Scraped item: {title}")
        save_item(category_id, {"title": title, "details": details})
    except Exception as e:
        print(f"Failed to scrape details: {e}")

async def process_category_list(page: Page, category_id, sub_item_xpath):
    """Iterates through every item found in a category-specific list page."""
    sub_items = page.locator(f'xpath={sub_item_xpath}')
    try:
        await sub_items.first.wait_for(state="attached", timeout=10000)
    except:
        return

    count = await sub_items.count()
    print(f"Processing category list with {count} items")

    for i in range(count):
        try:
            # Re-locate to avoid stale elements after navigation
            item = page.locator(f'xpath={sub_item_xpath}').nth(i)
            await item.wait_for(state="attached")

            # Download item thumbnail
            img_path = await download_media(page, item, f"category_{category_id}_item_{i}")

            # Navigate into item details
            await item.click()
            await page.wait_for_load_state("networkidle")

            # Scrape metadata and link the image
            await scrape_item_details(page, category_id, img_path)

            # Return to list
            await page.go_back()
            await page.wait_for_selector(f'xpath={sub_item_xpath}', timeout=10000)
        except Exception as e:
            print(f"Error on sub-item {i}: {e}")
            # Exit if we are completely lost
            if page.url == BASE_URL: break

async def process_section(page: Page, xpath, name):
    """Processes a major section on the homepage (like 'Featured', 'New Releases', etc.)."""
    print(f"--- Section: {name} ---")
    container = page.locator(f'xpath={xpath}')
    await container.wait_for(state="attached", timeout=15000)

    count = await container.locator('xpath=./div').count()
    for i in range(count):
        try:
            # Re-locate container and nth item
            container_locator = page.locator(f'xpath={xpath}/div')
            item = container_locator.nth(i)
            await item.wait_for(state="attached")

            # Capture section image
            img_path = await download_media(page, item, f"section_{name}_{i}")

            # Enter the item/category
            await item.click()
            await page.wait_for_load_state("networkidle")

            # Check if we landed on a category list or a specific item details page
            # Category pages usually have a title div at this specific XPath
            cat_title_loc = page.locator('xpath=//*[@id="main-app"]/div[2]/div[2]/main/div[2]/div/div')
            if await cat_title_loc.count() > 0:
                cat_name = await cat_title_loc.inner_text()
                cid = save_category(cat_name)
                
                # Determine sub-item path (varies by section structure)
                sub_path = '//*[@id="main-app"]/div[2]/div[2]/main/div[3]/div/div/div/div'
                if name != "Categories":
                    sub_path = '//*[@id="main-app"]/div[2]/div[2]/main/div[2]/div/div/div/div'

                await process_category_list(page, cid, sub_path)
            else:
                # Direct item page
                cid = save_category(name)
                await scrape_item_details(page, cid, img_path)

            # Return to homepage to continue with next item
            await page.go_back()
            # If go_back doesn't work well, page.goto(BASE_URL) could be used but is slower
            await container.wait_for(state="attached", timeout=10000)
        except Exception as e:
            print(f"Error on section item {i}: {e}")
            await page.goto(BASE_URL)
            await scroll_page(page)

async def run_scraper():
    """Main setup and execution flow for the Exxen scraper."""
    async with async_playwright() as p:
        print("Launching professional scraper...")
        browser = await p.chromium.launch(headless=True)
        # Use a real User-Agent to avoid detection
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        page = await context.new_page()

        # Apply stealth patches
        await Stealth().apply_stealth_async(page)

        print(f"Navigating to {BASE_URL}")
        await page.goto(BASE_URL, wait_until="networkidle")

        # Clear cookie consent banner
        try:
            btn = page.get_by_text("Accept necessary only", exact=True)
            if await btn.is_visible(timeout=3000):
                await btn.click()
                print("Cookies accepted.")
        except: pass

        await scroll_page(page)

        # Homepage sections and their XPaths
        sections = [
            ('//*[@id="main-app"]/div[2]/main/div/div[4]/div/div[1]/div', "Categories"),
            ('//*[@id="main-app"]/div[2]/main/div/div[3]/div/div[1]/div', "Featured"),
            ('//*[@id="main-app"]/div[2]/main/div/div[5]/div/div[1]', "Reality")
        ]

        for xpath, name in sections:
            try:
                await process_section(page, xpath, name)
            except Exception as e:
                print(f"Section {name} failed: {e}")

        await browser.close()
        print("Scraping operation finished.")

if __name__ == "__main__":
    asyncio.run(run_scraper())
