# Scraper for finding components from external resources if not already in a database

#potential websites:
#https://www.findchips.com/


import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel

class ScrapedComponent(BaseModel):
    part_number: str
    datasheet_url: str
    source: str

def fetch_datasheet_url(part_number: str) -> ScrapedComponent | None:
    part_number = part_number.upper()

    try: 
        url = f"https://www.datasheetarchive.com/datasheet/{part_number}"
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        response.raise_for_status()  # Check if the request was successful

        soup = BeautifulSoup(response.text, "html.parser")
 
        a = soup.find('a', class_='download-datasheet')
        pdf_page = a['href']

        res = requests.get(pdf_page, allow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)

        if res.url:
            return ScrapedComponent(
                datasheet_url=res.url,
                source="datasheetarchive"
            )
        else:
            print(f"No datasheet found for {part_number} on DatasheetArchive.")
        

    except Exception as e:
        print(f"Something went wrong fetching datasheet for {part_number}: {e}")