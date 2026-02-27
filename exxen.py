from pydantic import BaseModel
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




os.makedirs("hotel_images", exist_ok=True)

#postgresql connection
def get_connection2():
    return psycopg2.connect(
        host="localhost",
        database="myScraperDatabase",
        user="scraper_user",
        password="pass123*",
        port="5432"
    )

#save data in postgresql
def saveCategory(data):
    """
    Inserts a category into the categories table if it doesn't exist,
    and returns its id for linking with items.
    """
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

########
#save data in postgresql
def saveItems(cateId, data):

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

    # rowcount tells us if something was inserted
    inserted = cur.rowcount > 0

    conn.commit()
    cur.close()
    conn.close()

    return inserted


async def configure_stealth_browser(page):
    await page.add_init_script("""
        // Hide webdriver flag
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });

        // Fake chrome runtime
        window.chrome = {
            runtime: {}
        };

        // Fake languages
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en']
        });

        // Fake plugins
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5]
        });

        // Fix permissions (important)
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) =>
            parameters.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : originalQuery(parameters);
    """)

#########################################################3
#child page
async def childPage(page, sub_item_xpath, cateId):
    """
    Scrape all sub-items inside the child page.
    Returns a list of collected titles.
    Logs errors but continues.
    """
    
    sub_items = page.locator(f'xpath={sub_item_xpath}')
    try:
        await sub_items.first.wait_for(state="attached", timeout=10000)
    except Exception as e:
        print(f"Child page sub-items did not appear: {e}")
       

    sub_count = await sub_items.count()
    print(f"Found {sub_count} sub-items on child page")
    
    for j in range(sub_count):
        success = False
        max_attempts = 3
        last_exception = None

        for attempt in range(max_attempts):
            try:
                # re-locate to avoid stale elements
                sub_items = page.locator(f'xpath={sub_item_xpath}')
                sub_item = sub_items.nth(j)

                await sub_item.wait_for(state="attached", timeout=5000)
                
                ################# 
                #First save the thumbs then click 
                # Check quickly if image is visible / attached
                try:
                    image = sub_item.locator("img")
                    if not await image.is_visible(timeout=2000):
                        print(f"Image not visible, skipping")
                        continue

                    src = await image.get_attribute("data-src", timeout=2000)

                    if not src:
                        src = await image.get_attribute("src", timeout=2000)

                    if not src:
                        srcset = await image.get_attribute("srcset", timeout=2000)
                        if srcset:
                            src = srcset.split(",")[-1].split(" ")[0]

                    if not src:
                        print(f"No src found for image, skipping")
                        continue
                   
                    # make sure src is full url
                    full_url = urljoin(page.url, src)
                    response = await page.context.request.get(full_url)

                    if response.ok:
                        content = await response.body()

                        # extract original filename from url
                        parsed_url = urlparse(full_url)
                        original_name = os.path.basename(parsed_url.path)

                        # if website hides filename (like ?w=200)
                        if not original_name:
                            original_name = "image.jpg"

                        # final save path
                        save_path = os.path.join("categories", original_name)

                        with open(save_path, "wb") as f:
                            f.write(content)

                        print(f"Downloaded as {original_name}")

                except Exception as e:
                    print(f"Skipping image due to error:", e)
                    continue
            

                await sub_item.click()
                await page.wait_for_load_state("networkidle")
                description = []
                # collect info (example: title)
                title = await page.locator('xpath=//*[@id="main-app"]/div[2]/main/div[1]/div[2]/p/span').inner_text()
                print(f"Sub-item {j+1} title:", title)
                desDivAddr = page.locator('xpath=//*[@id="main-app"]/div[2]/main/div[2]')
                await desDivAddr.wait_for(state="attached", timeout=10000)

                paragraphs = desDivAddr.locator('xpath=./p')

                p_count = await paragraphs.count()

                for pr in range(p_count):
                    p = paragraphs.nth(pr)
                    
                    try:
                        text = await p.inner_text()
                        description.append(text)
                    except Exception as e:
                        print(f"Paragraph {pr} skipped: {e}")
                
                #Get year
                yearAddr = page.locator('xpath=//*[@id="main-app"]/div[2]/main/div[1]/div[2]/div[1]/div[1]/span[1]')
                await yearAddr.wait_for(state="attached", timeout=10000)
                year = await yearAddr.inner_text()
               

                #Get part
                partAddr = page.locator('xpath=//*[@id="main-app"]/div[2]/main/div[1]/div[2]/div[1]/div[1]/span[3]')
                await partAddr.wait_for(state="attached", timeout=10000)
                part = await partAddr.inner_text()
               
                data = {
                    "title": title,  
                    "details": {     
                        "year": year,
                        "part": part,
                        "description": description
                    }
                }
                #save items in to database
                saveItems(cateId, data)


                # go back to sub-item list
                await page.go_back()
                await page.wait_for_selector(f'xpath={sub_item_xpath}')

                
                success = True
                break  # exit retry loop

            except Exception as e:
                last_exception = e
                print(f"Sub-item {j+1} attempt {attempt+1} failed: {e}, retrying...")
                await asyncio.sleep(2)

        if not success:
            print(f"Sub-item {j+1} could not be processed. Last error: {last_exception}")

#########################################################3
#Featured child page
async def featuredChild(page, sub_item_xpath, cateId):
    """
    Scrape all sub-items inside the child page.
    Returns a list of collected titles.
    Logs errors but continues.
    """
    
    sub_items = page.locator(f'xpath={sub_item_xpath}')
    try:
        await sub_items.first.wait_for(state="attached", timeout=10000)
    except Exception as e:
        print(f"Child page sub-items did not appear: {e}")
       

    sub_count = await sub_items.count()
    print(f"Found {sub_count} sub-items on child page")
    
    for j in range(sub_count):
        success = False
        max_attempts = 3
        last_exception = None

        for attempt in range(max_attempts):
            try:
                # re-locate to avoid stale elements
                sub_items = page.locator(f'xpath={sub_item_xpath}')
                sub_item = sub_items.nth(j)

                await sub_item.wait_for(state="attached", timeout=5000)

                ################# 
                #First save the thumbs then click 
                # Check quickly if image is visible / attached
                try:
                    image = sub_item.locator("img").first
                    if not await image.is_visible(timeout=2000):
                        print(f"Image not visible, skipping")
                        continue

                    src = await image.get_attribute("data-src", timeout=2000)

                    if not src:
                        src = await image.get_attribute("src", timeout=2000)

                    if not src:
                        srcset = await image.get_attribute("srcset", timeout=2000)
                        if srcset:
                            src = srcset.split(",")[-1].split(" ")[0]

                    if not src:
                        print(f"No src found for image, skipping")
                        continue
                   
                    # make sure src is full url
                    full_url = urljoin(page.url, src)
                    response = await page.context.request.get(full_url)

                    if response.ok:
                        content = await response.body()

                        # extract original filename from url
                        parsed_url = urlparse(full_url)
                        original_name = os.path.basename(parsed_url.path)

                        # if website hides filename (like ?w=200)
                        if not original_name:
                            original_name = "image.jpg"

                        # final save path
                        save_path = os.path.join("categories", original_name)

                        with open(save_path, "wb") as f:
                            f.write(content)

                        print(f"Downloaded as {original_name}")

                except Exception as e:
                    print(f"Skipping image due to error:", e)
                    continue

                await sub_item.click()
                await page.wait_for_load_state("networkidle")
                description = []
                # collect info (example: title)
                title = await page.locator('xpath=//*[@id="main-app"]/div[2]/main/div[1]/div[2]/p/span').inner_text()
                print(f"Sub-item {j+1} title:", title)
                desDivAddr = page.locator('xpath=//*[@id="main-app"]/div[2]/main/div[2]')
                await desDivAddr.wait_for(state="attached", timeout=10000)

                paragraphs = desDivAddr.locator('xpath=./p')

                p_count = await paragraphs.count()

                for pr in range(p_count):
                    p = paragraphs.nth(pr)
                    
                    try:
                        text = await p.inner_text()
                        description.append(text)
                    except Exception as e:
                        print(f"Paragraph {pr} skipped: {e}")
                
                #Get year
                yearAddr = page.locator('xpath=//*[@id="main-app"]/div[2]/main/div[1]/div[2]/div[1]/div[1]/span[1]')
                await yearAddr.wait_for(state="attached", timeout=10000)
                year = await yearAddr.inner_text()
               
                #Category
                cateAddr = page.locator('xpath=//*[@id="main-app"]/div[2]/main/div[1]/div[2]/div[1]/div[1]/span[3]')
                cate = None
                if await cateAddr.count() > 0:
                    try:
                        cate = await cateAddr.first.inner_text()
                    except Exception as e:
                        print("Category found but failed to read:", e)
                        cate = None
                else:
                    print("Category not found → skipping")

                #Get part
                partAddr = page.locator('xpath=//*[@id="main-app"]/div[2]/main/div[1]/div[2]/div[1]/div[1]/span[5]')
                part = None
                if await partAddr.count() > 0:
                    try:
                        part = await partAddr.first.inner_text()
                    except Exception as e:
                        print("Part found but failed to read:", e)
                        part = None
                else:
                    print("Part not found → continue")
               
                data = {
                    "title": title,  
                    "details": {     
                        "year": year,
                        "category": cate,
                        "part": part,
                        "description": description
                    }
                }
                #save items in to database
                saveItems(cateId, data)


                # go back to sub-item list
                await page.go_back()
                await page.wait_for_selector(f'xpath={sub_item_xpath}')

                
                success = True
                break  # exit retry loop

            except Exception as e:
                last_exception = e
                print(f"Sub-item {j+1} attempt {attempt+1} failed: {e}, retrying...")
                await asyncio.sleep(2)
            
        if not success:
            print(f"Sub-item {j+1} could not be processed. Last error: {last_exception}") 

#######################################################
#ech cateogry details
#########################################################3
#child page
async def eachCategory(page, parentPath, totalCategories):
    
    for i in range(totalCategories):

        success = False  # track if we managed to scrape this element
        max_attempts = 3

        for attempt in range(max_attempts):
            try:
                # Re-locate parent and children inside loop (React SPA)
                categoryDiv = page.locator(f'xpath={parentPath}')
                allCategories = categoryDiv.locator('xpath=./div')
                cate = allCategories.nth(i)

                # Wait until the child div is attached
                await cate.wait_for(state="attached", timeout=5000)

                # Click and wait for page to load
                await cate.click()
                await page.wait_for_load_state("networkidle")

                #mouse movement and scroll
                await page.mouse.move(
                    random.randint(200, 900),
                    random.randint(200, 700),
                    steps=random.randint(12, 30)
                )
                await asyncio.sleep(random.uniform(2.5, 5.5))
                await page.evaluate("""
                    async () => {
                        const step = 300;
                        while (window.scrollY + window.innerHeight < document.body.scrollHeight) {
                            window.scrollBy(0, step);
                            await new Promise(r => setTimeout(r, 200));
                        }
                    }
                """)

                # Scrape detail
                title = await page.locator('xpath=//*[@id="main-app"]/div[2]/div[2]/main/div[2]/div/div').inner_text()
                print(f"Category {i+1} title:", title)
                cateId = saveCategory(title)
                print("Cate id is:", cateId)
                #############
                #Process each
                #Get all items and click for each and get required info
                sub_item_xpath = '//*[@id="main-app"]/div[2]/div[2]/main/div[3]/div/div/div/div'
                await childPage(page, sub_item_xpath, cateId)
              
                #await page.pause()

                # Go back to list
                await page.go_back()
                await page.wait_for_selector(f'xpath={parentPath}')

                success = True
                break  # exit retry loop if successful

            except TimeoutError:
                print(f"Attempt {attempt+1} failed for category {i+1}, retrying...")
                await asyncio.sleep(2)  # wait a bit before retry

        if not success:
            print(f"Category {i+1} could not be scraped after {max_attempts} attempts, skipping.")
        break        
#####################################
#main scrap
async def run_scraper():
    
    listing_url = "https://www.exxen.com/"
    session_id = uuid.uuid4().hex
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--use-gl=swiftshader",
            "--enable-accelerated-2d-canvas"
            ], slow_mo=50 )
        """
        context = await browser.new_context(
            proxy={
                "server": "http://31.59.20.176:6754",
                "username": "bvcfwjos",
                "password": "84cwozw7tlgh"
            }
        )
        """
        context = await browser.new_context(
        )

        
        
        page = await context.new_page()

        stealth = Stealth()
        
        # STEP 1: OPEN LISTING PAGE
        await page.goto(listing_url, wait_until="domcontentloaded")
        await page.screenshot(
            path="full_page.png",
            full_page=True
        )

        
        #check if there is a popup and click 
        try:
            accept_btn = page.get_by_text("Accept necessary only", exact=True)

            await accept_btn.first.wait_for(timeout=50000)
            await accept_btn.first.click()

            print("Cookie popup accepted")

        except:
            print("Cookie popup not found (safe)")
        """
        #Login part
        try:
            login = page.get_by_role("link", name="Log In")

            await login.wait_for(timeout=5000)
            await login.click()

            print("Login button Clicked")

        except:
            print("Something happend to login button")

        
        try:
            await page.locator('xpath=//*[@id="main-app"]/div/main/div[2]/form/div[1]/div/div/input').wait_for(timeout=10000)

            await page.locator('xpath=//*[@id="main-app"]/div/main/div[2]/form/div[1]/div/div/input').fill("baratijumakhan@gmail.com")
            await page.locator('xpath=//*[@id="main-app"]/div/main/div[2]/form/div[2]/div/div/div/input').fill("pass123*")

            await page.get_by_text("Log In", exact=True).click()

            # wait until login success
            await page.wait_for_load_state("networkidle")

            print("Login Success")

        except Exception as e:
            print("Login Failed:", e)
        """
        await page.wait_for_load_state("networkidle")


        #mouse movement and scroll
        await page.mouse.move(
            random.randint(200, 900),
            random.randint(200, 700),
            steps=random.randint(12, 30)
        )
        await asyncio.sleep(random.uniform(2.5, 5.5))
        await page.evaluate("""
            async () => {
                const step = 300;
                while (window.scrollY + window.innerHeight < document.body.scrollHeight) {
                    window.scrollBy(0, step);
                    await new Promise(r => setTimeout(r, 200));
                }
            }
        """)
        
        """
        await page.goto("https://api.ipify.org?format=text")
        print("Proxy IP:", await page.text_content("body"))
        await page.pause()
        """
        #categories start
        ################################################################
        try:
            
            parentPath = '//*[@id="main-app"]/div[2]/main/div/div[4]/div/div[1]/div'
            categoryDiv = page.locator(f'xpath={parentPath}')
            await categoryDiv.wait_for(state="attached", timeout=60000)

            tcategoryDiv = await categoryDiv.count()

            if tcategoryDiv > 0:
                print("Div Categories found:", tcategoryDiv)

                allCategories = categoryDiv.locator('xpath=./div')
                await allCategories.first.wait_for(state="attached", timeout=60000)

                tallCategories = await allCategories.count()

                if tallCategories > 0:
                    print("All categories found:", tallCategories)
                    
                    #########################
                    #Process each category
                    sub_results = await eachCategory(page, parentPath, tallCategories)
                    print("##############################################")
                    print("All data from categories fetched successfully")
                else:
                    print("No categories found 0")

            else:
                print("Div category not found 0")
               
        except Exception as e:
            print("The error my friend is:", e)   
        #categories end     
        #############################################################
        

        #Featured start
        ################################################################
        try:
            
            parentPath = '//*[@id="main-app"]/div[2]/main/div/div[3]/div/div[1]/div'
            featuredDiv = page.locator(f'xpath={parentPath}')
            await featuredDiv.wait_for(state="attached", timeout=60000)

            tfeaturedDiv = await featuredDiv.count()

            if tfeaturedDiv > 0:
                print("Div Featured found:", tfeaturedDiv)

                mainfeaturedDiv = featuredDiv.locator('xpath=./div[16]')
                await mainfeaturedDiv.first.wait_for(state="attached", timeout=60000)

                tfeaturedDiv = await mainfeaturedDiv.count()

                if tfeaturedDiv > 0:
                    print("All featured Address found:", tfeaturedDiv)
                    
                    # Click and wait for page to load
                    await mainfeaturedDiv.click()
                    await page.wait_for_load_state("networkidle")

                    #mouse movement and scroll
                    await page.mouse.move(
                        random.randint(200, 900),
                        random.randint(200, 700),
                        steps=random.randint(12, 30)
                    )
                    await asyncio.sleep(random.uniform(2.5, 5.5))
                    await page.evaluate("""
                        async () => {
                            const step = 300;
                            while (window.scrollY + window.innerHeight < document.body.scrollHeight) {
                                window.scrollBy(0, step);
                                await new Promise(r => setTimeout(r, 200));
                            }
                        }
                    """)
                    cateId = saveCategory("Featured")
                    #############
                    #Process each
                    #Get all items and click for each and get required info
                    sub_item_xpath = '//*[@id="main-app"]/div[2]/div[2]/main/div[2]/div/div/div/div'
                    await featuredChild(page, sub_item_xpath, cateId)
                
                    #await page.pause()

                    # Go back to list
                    await page.go_back()
                    await page.wait_for_selector(f'xpath={parentPath}')

                    print("##############################################")
                    print("All featured data fetched successfully")    
                else:
                    print("No featured address found 0")

            else:
                print("Div featured not found 0")
               
        except Exception as e:
            print("The error my friend is:", e)   
        #Featured end     
        #############################################################


        #Reality start
        ################################################################
        try:
            
            parentPath = '//*[@id="main-app"]/div[2]/main/div/div[5]/div/div[1]'
            realityDiv = page.locator(f'xpath={parentPath}')
            await realityDiv.wait_for(state="attached", timeout=60000)

            trealityDiv = await realityDiv.count()

            if trealityDiv > 0:
                print("Div Reality found:", trealityDiv)

                mainRealityDiv = realityDiv.locator('xpath=./div/div[16]')
                await mainRealityDiv.first.wait_for(state="attached", timeout=60000)

                tmainRealityDiv = await mainRealityDiv.count()

                if tmainRealityDiv > 0:
                    print("All Reality Address source found:", tmainRealityDiv)
                    
                    # Click and wait for page to load
                    await mainRealityDiv.click()
                    await page.wait_for_load_state("networkidle")

                    #mouse movement and scroll
                    await page.mouse.move(
                        random.randint(200, 900),
                        random.randint(200, 700),
                        steps=random.randint(12, 30)
                    )
                    await asyncio.sleep(random.uniform(2.5, 5.5))
                    await page.evaluate("""
                        async () => {
                            const step = 300;
                            while (window.scrollY + window.innerHeight < document.body.scrollHeight) {
                                window.scrollBy(0, step);
                                await new Promise(r => setTimeout(r, 200));
                            }
                        }
                    """)
                    cateId = saveCategory("Reality")
                    #############
                    #Process each
                    #Get all items and click for each and get required info
                    sub_item_xpath = '//*[@id="main-app"]/div[2]/div[2]/main/div[2]/div/div/div/div'
                    await featuredChild(page, sub_item_xpath, cateId)
                
                    #await page.pause()

                    # Go back to list
                    await page.go_back()
                    await page.wait_for_selector(f'xpath={parentPath}')

                    print("##############################################")
                    print("All reality data fetched successfully")    
                else:
                    print("No featured address found 0")

            else:
                print("Div featured not found 0")
               
        except Exception as e:
            print("The error my friend is:", e)   
        #Reality end     
        #############################################################
                   
        await browser.close()
       

    

asyncio.run(run_scraper())
