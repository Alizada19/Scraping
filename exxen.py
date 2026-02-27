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

# Load environment variables from .env file
load_dotenv()

# --- CONFIGURATION ---
BASE_URL = "https://www.exxen.com/"
MEDIA_DIR = "media_assets"
os.makedirs(MEDIA_DIR, exist_ok=True)

#postgresql connection
def get_connection2():
    """Returns a connection to the PostgreSQL database using environment variables."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        database=os.getenv("DB_NAME", "myScraperDatabase"),
        user=os.getenv("DB_USER", "scraper_user"),
        password=os.getenv("DB_PASS", "pass123*"),
        port=os.getenv("DB_PORT", "5432")
    )

#save data in postgresql
def saveCategory(name):
    """
    Inserts a category into the categories table if it doesn't exist,
    and returns its id for linking with items.
    """
    try:
        conn = get_connection2()
        cur = conn.cursor()

        # Insert category or do nothing if it exists, then return its id
        query = """
        INSERT INTO categories (category_name)
        VALUES (%s)
        ON CONFLICT (category_name) DO NOTHING
        RETURNING id;
        """

        cur.execute(query, (name,))
        result = cur.fetchone()

        if result:
            category_id = result[0]  # ID from INSERT
        else:
            # Category already exists → fetch id
            cur.execute("SELECT id FROM categories WHERE category_name = %s", (name,))
            category_id = cur.fetchone()[0]

        conn.commit()
        cur.close()
        conn.close()
        return category_id
    except Exception as e:
        print(f"Database error (saveCategory): {e}. Falling back to random ID for local save.")
        return random.randint(1000, 9999)

########
#save data in postgresql
def saveItems(cateId, data):
    """
    Saves item details to the database or appends to a local JSON file if DB fails.
    """
    try:
        conn = get_connection2()
        cur = conn.cursor()

        title = data["title"]
        details = data["details"]
        json_data = json.dumps(details)

        query = """
            INSERT INTO items (category_id, title, details)
            VALUES (%s, %s, %s)
            ON CONFLICT (category_id, title)
            DO NOTHING;
        """

        cur.execute(query, (cateId, title, json_data))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Database error (saveItems): {e}. Saving to local results.json instead.")
        results = []
        if os.path.exists("results.json"):
            try:
                with open("results.json", "r", encoding="utf-8") as f:
                    results = json.load(f)
            except: pass

        results.append({"category_id": cateId, **data})
        with open("results.json", "w", encoding="utf-8") as f:
            json.dump(results, f, indent=4, ensure_ascii=False)

# --- SCRAPING FUNCTIONS ---

async def scroll_page(page: Page):
    """Slowly scrolls down the page to trigger lazy loading."""
    await page.evaluate("""
        async () => {
            for (let i = 0; i < 8; i++) {
                window.scrollBy(0, 600);
                await new Promise(r => setTimeout(r, 250));
            }
        }
    """)

async def downloadMedia(page: Page, locator, prefix):
    """Identifies and downloads the highest resolution image."""
    try:
        img = locator.locator("img").first
        if not await img.is_visible(): return None

        # Check srcset (best), then data-src, then regular src
        src = await img.get_attribute("srcset")
        if src: src = src.split(",")[-1].split(" ")[0]
        if not src: src = await img.get_attribute("data-src")
        if not src: src = await img.get_attribute("src")

        if not src: return None

        url = urljoin(page.url, src)
        response = await page.context.request.get(url)
        if response.ok:
            # Get extension
            ext = os.path.splitext(urlparse(url).path)[1].split('?')[0] or ".jpg"
            filename = f"{prefix}_{uuid.uuid4().hex[:8]}{ext}"

            filepath = os.path.join(MEDIA_DIR, filename)
            with open(filepath, "wb") as f:
                f.write(await response.body())
            return filepath
    except Exception as e:
        print(f"Media download failed: {e}")
    return None

#########################################################3
#child page
async def childPage(page: Page, category_id, item_image_path=None):
    """
    Scrapes metadata and description from an item detail page.
    """
    try:
        # Title
        title_span = page.locator('#main-app main p span').first
        title = await title_span.inner_text(timeout=5000)

        # Metadata (Year, Category, Seasons)
        meta_spans = page.locator('#main-app main div div div div span')
        texts = [t.strip() for t in await meta_spans.all_inner_texts() if t.strip()]

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
                if details["category"] == "N/A": details["category"] = t

        # Description paragraphs
        desc_p = page.locator('#main-app main div[class*="Spacing/md"] p')
        if await desc_p.count() == 0:
            desc_p = page.locator('xpath=//*[@id="main-app"]/div[2]/main/div[2]/p')

        paragraphs = await desc_p.all_inner_texts()
        details["description"] = [p.strip() for p in paragraphs if len(p.strip()) > 20]

        data = {"title": title, "details": details}
        print(f"Scraped item: {title}")
        saveItems(category_id, data)

    except Exception as e:
        print(f"Failed to scrape details: {e}")

async def processCategoryList(page: Page, category_id, sub_item_xpath):
    """Iterates through every item found in a category folder."""
    sub_items = page.locator(f'xpath={sub_item_xpath}')
    try:
        await sub_items.first.wait_for(state="attached", timeout=10000)
    except: return

    count = await sub_items.count()
    print(f"Processing folder with {count} items")

    for i in range(count):
        try:
            item = page.locator(f'xpath={sub_item_xpath}').nth(i)
            await item.wait_for(state="attached")

            img_path = await downloadMedia(page, item, f"cat_{category_id}_item_{i}")

            await item.click()
            await page.wait_for_load_state("networkidle")

            await childPage(page, category_id, img_path)

            await page.go_back()
            await page.wait_for_selector(f'xpath={sub_item_xpath}', timeout=10000)
        except Exception as e:
            print(f"Error on sub-item {i}: {e}")
            if page.url == BASE_URL: break

async def processSection(page: Page, xpath, name):
    """Processes a major section (Categories, Featured, Reality)."""
    print(f"--- Section: {name} ---")
    container = page.locator(f'xpath={xpath}')
    await container.wait_for(state="attached", timeout=15000)

    count = await container.locator('xpath=./div').count()
    for i in range(count):
        try:
            item = page.locator(f'xpath={xpath}/div').nth(i)
            await item.wait_for(state="attached")

            img_path = await downloadMedia(page, item, f"section_{name}_{i}")

            await item.click()
            await page.wait_for_load_state("networkidle")

            # Check if it is a category list or direct item
            cat_title_loc = page.locator('xpath=//*[@id="main-app"]/div[2]/div[2]/main/div[2]/div/div')
            if await cat_title_loc.count() > 0:
                cat_name = await cat_title_loc.inner_text()
                cid = saveCategory(cat_name)
                
                sub_path = '//*[@id="main-app"]/div[2]/div[2]/main/div[3]/div/div/div/div'
                if name != "Categories":
                    sub_path = '//*[@id="main-app"]/div[2]/div[2]/main/div[2]/div/div/div/div'

                await processCategoryList(page, cid, sub_path)
            else:
                cid = saveCategory(name)
                await childPage(page, cid, img_path)

            await page.goto(BASE_URL, wait_until="networkidle")
            await scroll_page(page)
            await page.locator(f'xpath={xpath}').wait_for(state="attached")
        except Exception as e:
            print(f"Error on item {i}: {e}")
            await page.goto(BASE_URL)

#####################################
#main scrap
async def run_scraper():
    """Main execution point for the Exxen scraper."""
    async with async_playwright() as p:
        print("Launching browser...")
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        page = await context.new_page()

        # Apply stealth patches
        await Stealth().apply_stealth_async(page)

        print(f"Opening {BASE_URL}")
        await page.goto(BASE_URL, wait_until="networkidle")

        # Clear cookie popup
        try:
            btn = page.get_by_text("Accept necessary only", exact=True)
            if await btn.is_visible(timeout=3000): await btn.click()
        except: pass

        await scroll_page(page)

        # Main sections
        sections = [
            ('//*[@id="main-app"]/div[2]/main/div/div[4]/div/div[1]/div', "Categories"),
            ('//*[@id="main-app"]/div[2]/main/div/div[3]/div/div[1]/div', "Featured"),
            ('//*[@id="main-app"]/div[2]/main/div/div[5]/div/div[1]', "Reality")
        ]

        for xpath, name in sections:
            try:
                await processSection(page, xpath, name)
            except Exception as e:
                print(f"Section {name} failed: {e}")

        await browser.close()
        print("Scraping finished!")

if __name__ == "__main__":
    asyncio.run(run_scraper())
