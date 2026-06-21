# Scraper for finding datasheet urls from external resources if not already in the database 

# Scrape #1: DatasheetArchive
# Scrape #2: ....
# Scrape #3: ....

# ~3s fetch time for datasheetarchive

#potential websites:
#https://www.findchips.com/

import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel

class ScrapedComponent(BaseModel):
    datasheet_url: str
    source: str

def fetch_datasheet_url(part_number: str) -> ScrapedComponent | None:
    part_number = part_number.upper()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    # Scrape #1: DatasheetArchive
    try: 
        url = f"https://www.datasheetarchive.com/datasheet/{part_number}"
        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()  # Check if the request was successful

        soup = BeautifulSoup(response.text, "html.parser")
 
        a = soup.find('a', class_='download-datasheet')
        pdf_page = a['href']

        res = requests.get(pdf_page, allow_redirects=True, headers=headers, timeout=5)

        if res.url:
            return ScrapedComponent(
                datasheet_url=res.url,
                source="datasheetarchive"
            )
    except Exception as e:
        print(f"Scrape #1 (DatasheetArchive) failed for {part_number}: {e}")



    # Scrape #2: ....
    try:
        print('')

    except Exception as e:
        print(f"Scrape #2 () failed for {part_number}: {e}")




    # Scrape #3: ....
    try:
        print('')

    except Exception as e:
        print(f"Scrape #3 () failed for {part_number}: {e}")

    return None 
