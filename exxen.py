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

#################
# Global list to store all records
all_records = []
    
#########################################################3
#child page
async def childPage(page, sub_item_xpath, cateId,cateName):
    director=""
    print(f"############################### Category {cateName} Started ..................................")
    """
    Scrape all sub-items inside the child page.
    Returns a list of collected titles.
    Logs errors but continues.
    """
    
    try:

        try:    
            sub_items = page.locator(f'xpath={sub_item_xpath}')
            await sub_items.first.wait_for(state="attached", timeout=10000)
        except Exception as e:
            print(f"Could not find the locator my friend error is: {e}")

        sub_count = await sub_items.count()
        print(f"Found {sub_count} Series")
        
        for j in range(sub_count):
            series_data = []
            single_data = None
            print(f"############################### Series {j+1} Started ..................................")
            
            try:
                # re-locate to avoid stale elements
                sub_items = page.locator(f'xpath={sub_item_xpath}')

                tsub_items = await sub_items.count()
                if tsub_items > 0:
                    
                    sub_item = sub_items.nth(j)

                    await sub_item.wait_for(state="attached", timeout=5000)
                    
                    try:
                        
                        await sub_item.click()
                        await page.wait_for_load_state("networkidle", timeout=60000)
                        #mouse movement and scroll
                        await page.mouse.move(
                            random.randint(200, 900),
                            random.randint(200, 700),
                            steps=random.randint(12, 30)
                        )
                        await asyncio.sleep(random.uniform(2.5, 5.5))
                        #scroll page
                        scroll_height = await page.evaluate("document.body.scrollHeight")
                        current_pos = 0

                        while current_pos < scroll_height:
                            step = random.randint(200, 400)
                            current_pos += step
                            await page.evaluate(f"window.scrollTo(0, {current_pos})")
                            await asyncio.sleep(random.uniform(0.1, 0.3))
                            
                            # update scroll height in case page loads more content
                            scroll_height = await page.evaluate("document.body.scrollHeight")

                        
                        
                        ###############
                        #Get video and wait until finishes
                        try: 
                            print("Waiting for video to be finished.........")
                            video = page.locator('xpath=//*[@id="main-app"]/div[2]/main/div[1]/div[1]/video')
                            tvideo = await video.count()

                            if tvideo > 0:
                                vid = video.first
                                await vid.wait_for()

                                # wait until video actually starts playing
                                await page.wait_for_function(
                                    "v => v.currentTime > 0",
                                    arg=await vid.element_handle(),
                                    timeout=30000
                                )

                                try:
                                    #  wait until video reaches near end
                                    await page.wait_for_function(
                                        "v => v.duration > 0 && v.currentTime >= v.duration - 0.5",
                                        arg=await vid.element_handle(),
                                        timeout=120000
                                    )
                                except:
                                    print("Video did not fully finish, fallback to timeout")

                                    # fallback (your original idea)
                                    duration = await vid.evaluate("v => v.duration")
                                    if duration and duration == duration:
                                        await page.wait_for_timeout(int((duration + 1) * 1100))

                                # optional: wait for next content (image)
                                await page.wait_for_timeout(1000)
                                print("Video finished ######################################################################")
                            else:
                                print("video not found my")    
                        except Exception as e:
                            print("Could not wait for the video ignoring...error is", e)

                        
                        ################# 
                        #Get full image
                        src=""
                        
                        mimage = page.locator('xpath=//*[@id="main-app"]/div[2]/main/div[1]/div[1]')
                        tmimage = await mimage.count()
                        if tmimage > 0:

                            image1 = mimage.locator("img").first
                            src = await image1.get_attribute("src", timeout=6000)
                            print("####################Main IMage is: ", src)
                        else:
                            src = ""
                            print("Main Image not found")


                        description = []

                        # collect info (example: title)
                        title = page.locator('xpath=//*[@id="main-app"]/div[2]/main/div[1]/div[2]/p/span')
                        ttitle = await title.count()
                        if ttitle >0:
                            title = await title.inner_text()
                            print(f"Sub-item {j+1} title:", title)
                        else:
                            print("Title not found")    
                            title =""

                        

                        
                        
                        #Get Descriptioin        
                        desDivAddr = page.locator('xpath=//*[@id="main-app"]/div[2]/main/div[2]')
                        tdesDivAddr = await desDivAddr.count()
                        
                        if tdesDivAddr > 0:

                            paragraphs = desDivAddr.locator('xpath=./p')

                            p_count = await paragraphs.count()

                            
                            cast=""
                            director=""

                            for pr in range(p_count):
                                p = paragraphs.nth(pr)
                                
                                try:
                                    text = await p.inner_text()

                                    #Check if Cast: found in the text
                                    if "Oyuncular:" in text:
                                        cast = text
                                        print("Cast found: ", cast)
                                    
                                    #Check if Director: found in the text
                                    if "Yönetmen:" in text:
                                        director = text

                                    description.append(text)
                                except Exception as e:
                                    print(f"Paragraph {pr} skipped: {e}")
                        
                        else:
                            print("Description not found my friend!")

                        #Get year
                        yearAddr = page.locator('xpath=//*[@id="main-app"]/div[2]/main/div[1]/div[2]/div[1]/div[1]/span[1]')
                        yearTotal = await yearAddr.count()
                        if yearTotal > 0:

                            year = await yearAddr.inner_text()
                            
                        else:
                            print("Year not found")
                            year=""
                    
                        #############################################################
                        #check the season parts
                        seasonDropDown = page.locator('xpath=//*[@id="main-app"]/div[2]/main/div[3]/div[2]/div[1]/div[1]')
                        tseasonDropDown = await seasonDropDown.count()

                        if tseasonDropDown > 0:

                            print("Multi Season Dropdown Found:")

                            await seasonDropDown.click()

                            seasonList = page.locator('xpath=//*[@id="main-app"]/div[2]/main/div[3]/div[2]/div[1]/div[2]/div/div')
                            tseasonList = await seasonList.count()
                            if tseasonList > 0:
                                tseasonList
                            else:
                                print("Season list not found")    



                            print("Open new tab to get each season details.....")

                            for m in range(tseasonList):
                                print(f"############################### Season {m} Started ..................................")

                                try:
                                    seasonTempPage = await page.context.new_page()
                                    await seasonTempPage.goto(page.url)

                                    print("Season temp page opened .....")

                                    await seasonTempPage.wait_for_load_state("domcontentloaded")
                                    #mouse movement and scroll
                                    await seasonTempPage.mouse.move(
                                        random.randint(200, 900),
                                        random.randint(200, 700),
                                        steps=random.randint(12, 30)
                                    )
                                    await asyncio.sleep(random.uniform(2.5, 5.5))

                                    #scroll page
                                    scroll_height = await seasonTempPage.evaluate("document.body.scrollHeight")
                                    current_pos = 0

                                    while current_pos < scroll_height:
                                        step = random.randint(200, 400)
                                        current_pos += step
                                        await seasonTempPage.evaluate(f"window.scrollTo(0, {current_pos})")
                                        await asyncio.sleep(random.uniform(0.1, 0.3))
                                        
                                        # update scroll height in case page loads more content
                                        scroll_height = await seasonTempPage.evaluate("document.body.scrollHeight")

                                    seasonDropDown = seasonTempPage.locator('xpath=//*[@id="main-app"]/div[2]/main/div[3]/div[2]/div[1]/div[1]')
                                    tseasonDropDown = await seasonDropDown.count()
                                    if tseasonDropDown > 0:
                                    
                                        await seasonDropDown.click()


                                        seasonList = seasonTempPage.locator('xpath=//*[@id="main-app"]/div[2]/main/div[3]/div[2]/div[1]/div[2]/div/div').nth(m)
                                        tseasonList = await seasonList.count()
                                        
                                        if tseasonList > 0:
                                            print("Season list found")

                                            
                                            try:

                                                await seasonList.click()
                                                    
                                                await seasonTempPage.wait_for_load_state("networkidle", timeout=60000)

                                                #mouse movement and scroll
                                                await seasonTempPage.mouse.move(
                                                    random.randint(200, 900),
                                                    random.randint(200, 700),
                                                    steps=random.randint(12, 30)
                                                )
                                                await asyncio.sleep(random.uniform(2.5, 5.5))

                                                #scroll page
                                                scroll_height = await seasonTempPage.evaluate("document.body.scrollHeight")
                                                current_pos = 0

                                                while current_pos < scroll_height:
                                                    step = random.randint(200, 400)
                                                    current_pos += step
                                                    await seasonTempPage.evaluate(f"window.scrollTo(0, {current_pos})")
                                                    await asyncio.sleep(random.uniform(0.1, 0.3))
                                                    
                                                    # update scroll height in case page loads more content
                                                    scroll_height = await seasonTempPage.evaluate("document.body.scrollHeight")

                                                try:
                                                    #season title
                                                    seasonTitleAddr = seasonTempPage.locator('xpath=//*[@id="main-app"]/div[2]/main/div[3]/div[2]/div[1]/p/span')
                                                    tseasonTitleAddr = await seasonTitleAddr.count()
                                                    if tseasonTitleAddr > 0:

                                                        seasonTitle = await seasonTitleAddr.inner_text()
                                                        print("Season Title is: ", seasonTitle)

                                                        #####################################
                                                        #Each season content start

                                                        
                                                        if cateName=="Yarışmalar" or cateName=="Belgeseller" or cateName=="Çocuklar" or cateName=="Programlar" or cateName=="Diziler":
                                                            
                                                            ###series
                                                            season_data = {
                                                                "season": seasonTitle,
                                                                "episodes": [],
                                                                "trailers": []
                                                            }
                                                            series_data.append(season_data)

                                                            #now get all the episodes
                                                            episodeAddr = seasonTempPage.locator('xpath=//*[@id="main-app"]/div[2]/main/div[3]/div[2]/div[2]/div')
                                                            ecount = await episodeAddr.count()
                                                            if ecount > 0:

                                                                print("Found episodes in this season: ", ecount)

                                                                for n in range(ecount):

                                                                    print(f"############################### episode {n} Started ..................................")     

                                                                    eachOne = seasonTempPage.locator('xpath=//*[@id="main-app"]/div[2]/main/div[3]/div[2]/div[2]/div').nth(n)

                                                                    episodeUrl=""
                                                                    ######################### First Duplicate the Current page click on edpisode get details and close the tub
                                                                    try:
                                                                        tempPage = await seasonTempPage.context.new_page()
                                                                        await tempPage.goto(seasonTempPage.url)
                                                                        print("Temp page opened .....")
                                                                        await tempPage.wait_for_load_state("domcontentloaded")
                                                                        #mouse movement and scroll
                                                                        await tempPage.mouse.move(
                                                                            random.randint(200, 900),
                                                                            random.randint(200, 700),
                                                                            steps=random.randint(12, 30)
                                                                        )
                                                                        await asyncio.sleep(random.uniform(2.5, 5.5))

                                                                        #scroll page
                                                                        scroll_height = await tempPage.evaluate("document.body.scrollHeight")
                                                                        current_pos = 0

                                                                        while current_pos < scroll_height:
                                                                            step = random.randint(200, 400)
                                                                            current_pos += step
                                                                            await tempPage.evaluate(f"window.scrollTo(0, {current_pos})")
                                                                            await asyncio.sleep(random.uniform(0.1, 0.3))
                                                                            
                                                                            # update scroll height in case page loads more content
                                                                            scroll_height = await tempPage.evaluate("document.body.scrollHeight")


                                                                        thumb = tempPage.locator('xpath=//*[@id="main-app"]/div[2]/main/div[3]/div[2]/div[2]/div').nth(n)
                                                                        tthumb = await thumb.count()
                                                                        if tthumb > 0:

                                                                            old_url = tempPage.url
                                                                            await thumb.click()
                                                                            await tempPage.wait_for_url(lambda url: url != old_url)

                                                                            episodeUrl = tempPage.url
                                                                            
                                                                            print("Episode url is:", episodeUrl)
                                                                        else:
                                                                            print("Episode thumbnial not found to click")

                                                                        if not tempPage.is_closed():    
                                                                            await tempPage.close()
                                                                        print("temp page closed")
                                                                        


                                                                    except Exception as e:
                                                                            print("Something happend in this episode my friend the errro is:", e)
                                                                            if not tempPage.is_closed():
                                                                                await tempPage.close()
                                                                    
                                                                    

                                                                    #Duplicate temp tub closed
                                                                    #######################

                                                                    etitleAdr = eachOne.locator('xpath=./div/div/div[1]/p[1]')
                                                                    tetitleAdr = await etitleAdr.count()
                                                                    if tetitleAdr > 0:

                                                                        try:
                                                                            await etitleAdr.first.wait_for(timeout=5000)
                                                                            etitle = await etitleAdr.inner_text()
                                                                            print("Episode title is: ", etitle)

                                                                        except Exception:
                                                                            print("etitel timeout error!!!!")

                                                                    else:
                                                                        etitle = ""
                                                                        print("episode title Not found")   


                                                                    #get abstraction
                                                                    abstractAdr = eachOne.locator('xpath=./div/button/div[2]/div/div/p[2]')
                                                                    tabstractAdr = await abstractAdr.count()
                                                                    if tabstractAdr > 0:
                                                                        abstract = await abstractAdr.inner_text()
                                                                        print("Episode abstract is: ", abstract)

                                                                    else:
                                                                        abstract = ""
                                                                        print("Abstract Not found") 

                                                                    
                                                                    

                                                                    #Get thumb image
                                                                    isrc=""
                                                                    simage = eachOne.locator('xpath=./div/button')
                                                                    tsimage = await simage.count()
                                                                    if tsimage > 0:
                                                                        image2 = simage.locator("img")
                                                                        isrc = await image2.get_attribute("src", timeout=2000)
                                                                        print("Episode image is: ", isrc)

                                                                    else:
                                                                        isrc = ""
                                                                        print("Episode Image not found")
                                                                        
                                                                    episode_info = {
                                                                        "title": etitle,
                                                                        "abstract": "",
                                                                        "synopsis": abstract,
                                                                        "mainImage": isrc,
                                                                        "episodeLink": episodeUrl
                                                                    }
                                                                    season_data["episodes"].append(episode_info)

                                                                    print(f"############################### episode {n} Finished ..................................")
                                                            else:
                                                                print("Not found → skipping")

                                                            
                                                            
                                                            
                                                            trailers = {
                                                                "title": title,
                                                                "abstract": "",
                                                                "synopsis": " ".join(description),
                                                                "mainImage": src,
                                                                "episodeLink": seasonTempPage.url
                                                            }
                                                            
                                                            season_data["trailers"].append(trailers)

                                                        else:    
                                                    
                                                            single_data = []
                                                            #single data
                                                            single_data = {
                                                                "mainImage": "",
                                                                "episodeLink": "",
                                                                "trailers": []
                                                            }

                                                            trailer_info = {
                                                                "title": title,
                                                                "abstract": "",
                                                                "synopsis": " ".join(description),
                                                                "mainImage": src,
                                                                "episodeLink": seasonTempPage.url
                                                            }

                                                            single_data["trailers"].append(trailer_info)


                                                        #each season content ends
                                                        ####################################

                                                    else:
                                                        print("Season Title not found")    
                                                        seasonTitle=""
                                                    
                                                    

                                                except Exception as e:
                                                    print("Can not get season details error is:", e)

                                            
                                            except Exception as e:
                                                    print("Inside the click season something happened error is:", e)        
                                                    await seasonTempPage.go_back()
                                                    await seasonTempPage.wait_for_load_state("networkidle", timeout=60000)
                                            
                                        else:
                                            print("Season list not found") 



                                    else:
                                        print("Target season not found")

                                    
                                    if not seasonTempPage.is_closed():
                                        await seasonTempPage.close()
                                    print("Closed duplicate multi season tab")

                                except Exception as e:
                                        print("Something happend in this season my friend the errro is:", e)
                                
                                print(f"############################### Season {m} Finished Successully #########################")

                                #Duplicate tub closed
                                #######################

                            



                            
                        else:
                            print("This series has onley 1 season....")    
                        
                            #Get part
                            seasonTitleAddr = page.locator('xpath=//*[@id="main-app"]/div[2]/main/div[3]/div[2]/div[1]/p/span')
                            tseasonTitleAddr = await seasonTitleAddr.count()
                            if tseasonTitleAddr > 0:
                
                                seasonTitle = await seasonTitleAddr.inner_text()

                            else:
                                seasonTitle = ""

                            series_data = None
                            single_data = None
                            if cateName=="Yarışmalar" or cateName=="Belgeseller" or cateName=="Çocuklar" or cateName=="Programlar" or cateName=="Diziler":
                                series_data = []
                                ###series
                                season_data = {
                                    "season": seasonTitle,
                                    "episodes": [],
                                    "trailers": []
                                }
                                series_data.append(season_data)

                                #now get all the episodes
                                episodeAddr = page.locator('xpath=//*[@id="main-app"]/div[2]/main/div[3]/div[2]/div[2]/div')
                                ecount = await episodeAddr.count()
                                if ecount > 0:
                                        
                                    print("Found total episode: ", ecount)

                                    for n in range(ecount):
                                        try:
                                            print(f"############################### episode {n} started ..................................")

                                            eachOne = page.locator('xpath=//*[@id="main-app"]/div[2]/main/div[3]/div[2]/div[2]/div').nth(n)

                                            episodeUrl=""
                                            ######################### First Duplicate the Current page click on edpisode get details and close the tub
                                            try:
                                                tempPage = await page.context.new_page()
                                                await tempPage.goto(page.url)
                                                print("Temp page opened .....")
                                                await tempPage.wait_for_load_state("domcontentloaded")
                                                #mouse movement and scroll
                                                await tempPage.mouse.move(
                                                    random.randint(200, 900),
                                                    random.randint(200, 700),
                                                    steps=random.randint(12, 30)
                                                )
                                                await asyncio.sleep(random.uniform(2.5, 5.5))
                                                #scroll page
                                                scroll_height = await tempPage.evaluate("document.body.scrollHeight")
                                                current_pos = 0

                                                while current_pos < scroll_height:
                                                    step = random.randint(200, 400)
                                                    current_pos += step
                                                    await tempPage.evaluate(f"window.scrollTo(0, {current_pos})")
                                                    await asyncio.sleep(random.uniform(0.1, 0.3))
                                                    
                                                    # update scroll height in case page loads more content
                                                    scroll_height = await tempPage.evaluate("document.body.scrollHeight")


                                                thumb = tempPage.locator('xpath=//*[@id="main-app"]/div[2]/main/div[3]/div[2]/div[2]/div').nth(n)
                                                tthumb = await thumb.count()
                                                if tthumb > 0:

                                                    old_url = tempPage.url
                                                    await thumb.click()
                                                    await tempPage.wait_for_url(lambda url: url != old_url)

                                                    episodeUrl = tempPage.url
                                                    
                                                    print("Episode url is:", episodeUrl)
                                                else:
                                                    print("Episode thumbnial not found to click")
                                                
                                                if not tempPage.is_closed():
                                                    await tempPage.close()
                                                print("Temp page closed")

                                            except Exception as e:
                                                    print("Something happend in this episode my friend the errro is:", e)
                                                    if not tempPage.is_closed():
                                                        await tempPage.close()
                                            
                                            #Duplicate tub closed
                                            #######################

                                            

                                            etitleAddr = eachOne.locator('xpath=./div/div/div[1]/p[1]')
                                            tetitleAddr = await etitleAddr.count()
                                            if tetitleAddr > 0:
                                                    try:
                                                        await etitleAddr.first.wait_for(timeout=5000)
                                                        etitle = await etitleAddr.inner_text()
                                                        print("Episode title is: ", etitle)

                                                    except Exception:
                                                        print("etitel timeout error!!!!")
                                            else:
                                                etitle = ""
                                                print("episode title Not found")   
                                            
                                        

                                            #get abstraction
                                            abstractAdr = eachOne.locator('xpath=./div/button/div[2]/div/div/p[2]')
                                            tabstractAdr = await abstractAdr.count()
                                            if tabstractAdr > 0:
                                                
                                                abstract = await abstractAdr.inner_text()
                                                print("Episode abstract is: ", abstract)

                                            else:
                                                abstract = ""
                                                print("Abstract Not found") 

                                            
                                            

                                            #Get thumb image
                                            isrc=""
                                            simage = eachOne.locator('xpath=./div/button')
                                            tsimage = await simage.count()
                                            if tsimage > 0:
                                                image2 = simage.locator("img")
                                                isrc = await image2.get_attribute("src", timeout=2000)

                                                print("Episode Image is: ", isrc)

                                            else:
                                                isrc = ""
                                                print("Episode Image not found")


                                            episode_info = {
                                                "title": etitle,
                                                "abstract": "",
                                                "synopsis": abstract,
                                                "mainImage": isrc,
                                                "episodeLink": episodeUrl
                                            }
                                            season_data["episodes"].append(episode_info)

                                            print(f"############################### episode {n} Finished ..................................")

                                        except Exception as e:
                                            print("something happend to episode details")
                                            

                                        
                                else:
                                    print("Not found → skipping")

                                                    
                                
                                
                                trailers = {
                                    "title": title,
                                    "abstract": "",
                                    "synopsis": " ".join(description),
                                    "mainImage": src,
                                    "episodeLink": page.url
                                }
                                
                                season_data["trailers"].append(trailers)

                            else:    
                        
                                single_data = []
                                #single data
                                single_data = {
                                    "mainImage": "",
                                    "episodeLink": "",
                                    "trailers": []
                                }

                                trailer_info = {
                                    "title": title,
                                    "abstract": "",
                                    "synopsis": "",
                                    "mainImage": src,
                                    "episodeLink": page.url
                                }

                                single_data["trailers"].append(trailer_info)

                        #Get url
                        pid =  page.url.split("/show/")[1].split("?")[0]
                        print("Page id is: ", pid)
                            
                        record = {
                            "refId": pid,
                            "refUrl": page.url,
                            "provider": "exxen",
                            "contentType": cateName,
                            "title": title,
                            "originalTitle": "",
                            "description": " ".join(description),
                            "genres": cateName,
                            "dubbingLanguages": "",
                            "subtitleLanguages": "",
                            "originCountries": "",
                            "ageGroup": "",
                            "productionYear": year,
                            "mainImage": src,
                            "posterImage": "",
                            "sliderImage": "",
                            "logoImage": "",
                            "imdbRanking": "",
                            "tages": "",
                            "director": director,
                            "crew": "",
                            "cast": cast,
                            "series": series_data,  
                            "single": single_data
                        }

                        all_records.append(record)

                        #save items in to database
                        #saveItems(cateId, data, all_records)


                        # go back to sub-item list
                        await page.go_back()
                        await page.wait_for_selector(f'xpath={sub_item_xpath}')

                        
                        

                    except Exception as e:
                        print("Some problem happend inside this series", e)
                        await page.go_back()
            
                else:
                    print("No item series found my friend")

            except Exception as e:
                print("The error is my friend",e)
                
            print(f"############################### Series {j+1} completed")
            

    except Exception as e:
        print(f"Error happend my frined it is: {e}")

    print(f"############################### Category {cateName} completed")
    
   # with open("exxen_data.json", "w", encoding="utf-8") as f:
    #    json.dump(all_records, f, ensure_ascii=False, indent=2)   
    #await page.pause()
#########################################################3

#######################################################
#ech cateogry details
#########################################################3
#child page
async def eachCategory(page, categories):
    
    for category in categories:

        categoryPage = await page.context.new_page()
        success = False
        for attempt in range(3):
            try:
                await categoryPage.goto(category)
                await categoryPage.wait_for_load_state("networkidle", timeout=60000)
                success = True
                break
            except Exception as e:
                print(f"Retry my friend {attempt+1} ...")  
                if attempt < 2:
                    await asyncio.sleep(10)
                    
        if not success:
            print("Skipping this:", category)
            continue   # go to next
                    
        #mouse movement and scroll
        await categoryPage.mouse.move(
            random.randint(200, 900),
            random.randint(200, 700),
            steps=random.randint(12, 30)
        )
        await asyncio.sleep(random.uniform(2.5, 5.5))
        #scroll page
        scroll_height = await categoryPage.evaluate("document.body.scrollHeight")
        current_pos = 0

        while current_pos < scroll_height:
            step = random.randint(200, 400)
            current_pos += step
            await categoryPage.evaluate(f"window.scrollTo(0, {current_pos})")
            await asyncio.sleep(random.uniform(0.1, 0.3))
            
            # update scroll height in case page loads more content
            scroll_height = await categoryPage.evaluate("document.body.scrollHeight")
        
        
        
        try:
            

            # Scrape detail
            title = categoryPage.locator('xpath=//*[@id="main-app"]/div[2]/div[2]/main/div[2]/div/div/span')
            ttitle = await title.count()
            if ttitle > 0:
                cateName = await title.inner_text()
                print(f"Category title:", cateName)
            else:
                print("Title not found")
                cateName = ""

            cateId = "tempId"#saveCategory(cateName)
            print("Cate id is:", cateId)
            #############
            #Process each
            #Get all items and click for each and get required info
            sub_item_xpath = '//*[@id="main-app"]/div[2]/div[2]/main/div[3]/div/div/div/div'
        
            await childPage(categoryPage, sub_item_xpath, cateId, cateName)
            


        except Exception as e:
            print("The error is my friend", e)

       
        print("Category page finished and closed")
        if not categoryPage.is_closed():
            await categoryPage.close()
        
               
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
                "server": "http://pr.oxylabs.io:7777",
                "username": "customer-alizada_ZeeRM-cc-tr-sessid-{session_id}-sesstime-10",
                "password": "_UC92JUyJgLyS"
            },
            
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
        await page.wait_for_load_state("networkidle", timeout=60000)
        
        #Change lanuage into turkish
        langList = page.locator('xpath=//*[@id="main-app"]/div[1]/header/div[1]/div[2]/button')
        tlangList = await langList.count()
        if tlangList > 0:

            print("Language Button found")

            await langList.click()

            langButton = page.locator('xpath=//*[@id="main-app"]/div[1]/header/div[1]/div[3]/button[2]')
            tlangButton = await langButton.count()
            if tlangButton > 0:
                    
                    print("Turkish language found")

                    await langButton.click()
                    await page.wait_for_load_state("networkidle", timeout=60000)
            else:
                print("Language button not found")    

        else:
            print("Language List not found")    


        #Login part
        """
        try:
            login = page.get_by_role("link", name="Log In")

            await login.wait_for(timeout=10000)
            await login.click()
            print("Login button Clicked")

            account = page.locator('xpath=/html/body/div[2]/div/div[2]/div/button/div/img') 
            taccount = await account.count()
            if taccount > 0:
                await account.wait_for(timeout=10000)
                await account.click()
            else:
                print("Can find the account settings")

        except:
            print("Something happend to login button")

        
        try:
            await page.locator('xpath=//*[@id="main-app"]/div/main/div[2]/form/div[1]/div/div/input').wait_for(timeout=10000)

            email = page.locator('xpath=//*[@id="main-app"]/div/main/div[2]/form/div[1]/div/div/input')
            password = page.locator('xpath=//*[@id="main-app"]/div/main/div[2]/form/div[2]/div/div/div/input')
            login_btn = page.get_by_text("Log In", exact=True)

            await email.type("sean.sat11@gmail.com", delay=500)
            await password.type("Sat@2025!$", delay=500)
            await login_btn.wait_for(state="visible")
            await page.wait_for_timeout(10000)

            await login_btn.click()
            
            print("Login Success")

        except Exception as e:
            print("Login Failed:", e)
        """
        await page.wait_for_load_state("networkidle", timeout=60000)


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
            
            categories = [
                #Competations
                "https://www.exxen.com/category/66335383a0e8450016ac79a6",

                #Documentaries
                "https://www.exxen.com/category/66336071a0e8450016ac79a8",

                #Kids
                "https://www.exxen.com/category/663360a4a0e84500190be217",

                #Programs
                "https://www.exxen.com/category/663360c623eec600165fe68c",

                #Series
                "https://www.exxen.com/category/663360e2a0e84500190be219"
            ]
        
                
            await eachCategory(page, categories)
           
            
        except Exception as e:
            print("Category level error is my friend :", e)   

        #Write content in to a file
        with open("exxen_data.json", "w", encoding="utf-8") as f:
            json.dump(all_records, f, ensure_ascii=False, indent=2)   
        await page.pause()
              
        #categories end     
        #############################################################
        
   
        #############################################################
        if not page.is_closed():
            await page.close()         
        await browser.close()
       
    
    

asyncio.run(run_scraper())