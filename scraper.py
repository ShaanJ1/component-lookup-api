# Scraper for finding components from external resources if not already in a database

#potential websites:
#https://www.findchips.com/


import requests
from bs4 import BeautifulSoup

def fetch_datasheet_url(part_number: str):
    part_number = part_number.upper()

    try: 
        url = f"https://www.datasheetarchive.com/datasheet/{part_number}"
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        response.raise_for_status()  # Check if the request was successful

        soup = BeautifulSoup(response.text, "html.parser")
 
        datasheet_link = soup.find('iframe', id="data")

        if datasheet_link["src"]:
            print("Found link!")

        else:
            print("No pdf link found")

        # if datasheet_link:
        #     return {
        #         "part_number": part_number,
        #         "datasheet_url": datasheet_link['href'],
        #         "source": "datasheetarchive"
        #     }
        # else:
        #     print(f"No datasheet found for {part_number} on DatasheetArchive.")
        

    except Exception as e:
        print(f"Something went wrong fetching datasheet for {part_number}: {e}")