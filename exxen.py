from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from urllib.parse import urljoin, urlparse
import asyncio
import random
import uuid
import re
import os
import psycopg2
import json
from dotenv import load_dotenv

# Load settings from .env file
load_dotenv()

os.makedirs("hotel_images", exist_ok=True)

#postgresql connection
def get_connection2():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        database=os.getenv("DB_NAME", "myScraperDatabase"),
        user=os.getenv("DB_USER", "scraper_user"),
        password=os.getenv("DB_PASS", "pass123*"),
        port=os.getenv("DB_PORT", "5432")
    )

#save data in postgresql
def saveCategory(data):
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

        cur.execute(query, (data,))
        result = cur.fetchone()

        if result:
            category_id = result[0]  # ID from INSERT
        else:
            # Category already exists → fetch id
            cur.execute("SELECT id FROM categories WHERE category_name = %s", (data,))
            category_id = cur.fetchone()[0]

        conn.commit()
        cur.close()
        conn.close()
        return category_id
    except Exception as e:
        print(f"Database error (saveCategory): {e}")
        return random.randint(1000, 9999)

########
#save data in postgresql
def saveItems(cateId, data):
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
        print(f"Database error (saveItems): {e}")
        # Local fallback if database is not available
        results = []
        if os.path.exists("results.json"):
            with open("results.json", "r", encoding="utf-8") as f:
                try: results = json.load(f)
                except: results = []
        results.append({"category_id": cateId, **data})
        with open("results.json", "w", encoding="utf-8") as f:
            json.dump(results, f, indent=4, ensure_ascii=False)

#########################################################3
#child page
async def childPage(page, sub_item_xpath, cateId):
    """
    Scrape all sub-items inside the child page.
    """
    sub_items = page.locator(f'xpath={sub_item_xpath}')
    try:
        await sub_items.first.wait_for(state="attached", timeout=10000)
    except: return

    sub_count = await sub_items.count()
    print(f"Found {sub_count} sub-items on child page")

    for j in range(sub_count):
        for attempt in range(3):
            try:
                sub_items = page.locator(f'xpath={sub_item_xpath}')
                sub_item = sub_items.nth(j)
                await sub_item.wait_for(state="attached", timeout=5000)

                await sub_item.click()
                await page.wait_for_load_state("networkidle")

                # collect info (example: title)
                title = await page.evaluate('() => document.querySelector("main p span")?.innerText || document.querySelector("h1")?.innerText || "Untitled"')
                print(f"Sub-item {j+1} title: {title}")

                # --- DOWNLOAD IMAGE AFTER CLICK ---
                try:
                    img_loc = page.locator('img[class*="object-cover"]').first
                    src = await img_loc.get_attribute("src")
                    if not src:
                        src = await img_loc.get_attribute("srcset")
                        if src: src = src.split(",")[-1].split(" ")[0]

                    if src:
                        full_url = urljoin(page.url, src)
                        response = await page.context.request.get(full_url)
                        if response.ok:
                            # Save with title name
                            safe_title = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')
                            save_path = f"hotel_images/{safe_title}.jpg"
                            with open(save_path, "wb") as f:
                                f.write(await response.body())
                            print(f"Downloaded image: {safe_title}.jpg")
                except: pass
                # ----------------------------------

                description = []
                desDivAddr = page.locator('xpath=//*[@id="main-app"]/div[2]/main/div[2]')
                paragraphs = desDivAddr.locator('xpath=./p')
                for pr in range(await paragraphs.count()):
                    txt = await paragraphs.nth(pr).inner_text()
                    if len(txt.strip()) > 10: description.append(txt.strip())

                # Metadata
                year, part = "N/A", "N/A"
                meta_spans = page.locator('#main-app main div div div div span')
                for i in range(await meta_spans.count()):
                    t = await meta_spans.nth(i).inner_text()
                    if t.isdigit() and len(t) == 4: year = t
                    elif "Season" in t or "Part" in t: part = t

                data = {"title": title, "details": {"year": year, "part": part, "description": description}}
                saveItems(cateId, data)

                await page.go_back()
                await page.wait_for_selector(f'xpath={sub_item_xpath}', timeout=10000)
                break
            except Exception as e:
                print(f"Attempt {attempt+1} failed for sub-item {j+1}: {e}")
                await page.goto("https://www.exxen.com/") # recovery

#########################################################3
#Featured child page
async def featuredChild(page, sub_item_xpath, cateId):
    """
    Scrape all sub-items inside the child page.
    """
    sub_items = page.locator(f'xpath={sub_item_xpath}')
    try:
        await sub_items.first.wait_for(state="attached", timeout=10000)
    except: return

    sub_count = await sub_items.count()
    print(f"Found {sub_count} items in section")

    for j in range(sub_count):
        for attempt in range(3):
            try:
                sub_items = page.locator(f'xpath={sub_item_xpath}')
                sub_item = sub_items.nth(j)
                await sub_item.wait_for(state="attached", timeout=5000)

                await sub_item.click()
                await page.wait_for_load_state("networkidle")

                title = await page.evaluate('() => document.querySelector("main p span")?.innerText || document.querySelector("h1")?.innerText || "Untitled"')
                print(f"Item {j+1}: {title}")

                # --- DOWNLOAD IMAGE AFTER CLICK ---
                try:
                    img_loc = page.locator('img[class*="object-cover"]').first
                    src = await img_loc.get_attribute("src")
                    if src:
                        full_url = urljoin(page.url, src)
                        response = await page.context.request.get(full_url)
                        if response.ok:
                            safe_title = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')
                            with open(f"hotel_images/{safe_title}.jpg", "wb") as f:
                                f.write(await response.body())
                except: pass
                # ----------------------------------

                description = []
                paragraphs = page.locator('xpath=//*[@id="main-app"]/div[2]/main/div[2]/p')
                for pr in range(await paragraphs.count()):
                    description.append(await paragraphs.nth(pr).inner_text())
                
                year, part = "N/A", "N/A"
                meta_spans = page.locator('#main-app main div div div div span')
                for i in range(await meta_spans.count()):
                    t = await meta_spans.nth(i).inner_text()
                    if t.isdigit() and len(t) == 4: year = t
                    elif "Season" in t or "Part" in t: part = t

                data = {"title": title, "details": {"year": year, "part": part, "description": description}}
                saveItems(cateId, data)

                await page.go_back()
                await page.wait_for_selector(f'xpath={sub_item_xpath}', timeout=10000)
                break
            except Exception as e:
                print(f"Item {j+1} error: {e}")
                await page.goto("https://www.exxen.com/")

#######################################################
#each category details
async def eachCategory(page, parentPath, totalCategories):
    for i in range(totalCategories):
        for attempt in range(3):
            try:
                categoryDiv = page.locator(f'xpath={parentPath}')
                cate = categoryDiv.locator('xpath=./div').nth(i)
                await cate.wait_for(state="attached", timeout=5000)

                await cate.click()
                await page.wait_for_load_state("networkidle")

                # Scroll to load items
                await page.evaluate("window.scrollBy(0, 500)")
                await asyncio.sleep(2)

                title = await page.locator('xpath=//*[@id="main-app"]/div[2]/div[2]/main/div[2]/div/div').inner_text()
                print(f"Category {i+1} title: {title}")
                cateId = saveCategory(title)

                sub_item_xpath = '//*[@id="main-app"]/div[2]/div[2]/main/div[3]/div/div/div/div'
                await childPage(page, sub_item_xpath, cateId)

                await page.go_back()
                await page.wait_for_selector(f'xpath={parentPath}', timeout=10000)
                break
            except Exception as e:
                print(f"Category {i+1} attempt {attempt+1} failed: {e}")
                await page.goto("https://www.exxen.com/")

#####################################
#main scrap
async def run_scraper():
    listing_url = "https://www.exxen.com/"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        page = await context.new_page()
        await Stealth().apply_stealth_async(page)

        print("Opening website...")
        await page.goto(listing_url, wait_until="networkidle")

        # Accept cookies
        try:
            await page.get_by_text("Accept necessary only", exact=True).click(timeout=5000)
        except: pass

        # Categories
        try:
            parentPath = '//*[@id="main-app"]/div[2]/main/div/div[4]/div/div[1]/div'
            categoryDiv = page.locator(f'xpath={parentPath}')
            await categoryDiv.wait_for(state="attached", timeout=10000)
            tallCategories = await categoryDiv.locator('xpath=./div').count()
            if tallCategories > 0:
                await eachCategory(page, parentPath, tallCategories)
        except Exception as e:
            print(f"Categories section error: {e}")

        # Featured
        try:
            parentPath = '//*[@id="main-app"]/div[2]/main/div/div[3]/div/div[1]/div'
            await featuredChild(page, parentPath + '/div', saveCategory("Featured"))
        except Exception as e:
            print(f"Featured section error: {e}")

        # Reality
        try:
            parentPath = '//*[@id="main-app"]/div[2]/main/div/div[5]/div/div[1]'
            await featuredChild(page, parentPath + '/div/div', saveCategory("Reality"))
        except Exception as e:
            print(f"Reality section error: {e}")

        await browser.close()
        print("Scraping finished!")

if __name__ == "__main__":
    asyncio.run(run_scraper())
