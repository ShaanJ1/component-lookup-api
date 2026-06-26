# Scraper for finding datasheet urls from external resources if not already in the database 
# Currently only scrapes from datasheet archive since most other sites have strict bot protection and I was unable to find alternatives

# Uses Google AI to parse PDF datasheets and extract specifications

import os
import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel

from typing import Any
import json

from dotenv import load_dotenv

from google import genai
from google.genai import types

load_dotenv()

client = genai.Client(
    api_key = os.getenv("GOOGLE_API_KEY")
)

models = ['gemini-3.5-flash', 'gemini-3-flash-preview', 'gemini-2.5-flash'] # try these models in order if one fails

class ScrapedComponent(BaseModel):
    part_number: str
    description: str | None
    specifications: dict[str, Any] | None
    datasheet_url: str
    source: str

# extract component specifications from a pdf datasheet
def parse_pdf(pdf_bytes: bytes, part_number: str, model_name: str) -> dict | None:  # fetch time ~20-60 seconds (depending on model)
    model_attempt = 0
    try:
        prompt = f"""
        You are extracting specifications from a pdf of an electronic component's datasheet.
        
        TARGET PART NUMBER: {part_number}

        Rules:
        1. The PDF may contain multiple part numbers, you must extract ONLY specifications that apply to {part_number}
        2. Never combine specifications from different part variants
        3. Ignore ordering tables
        4. Ignore package drawings
        5. Ignore legal notices
        6. Ignore marketing text
        7. Extract:
            - electrical characteristics
            - absolute maximum ratings
            - recommended operating conditions
            - timing characteristics
            - thermal characteristics
            - other specifications that are relevant to the part number and to the component's operation
        8. Normalize and preserve units (Examples: mA, V, ns, MHz, °C)
        9. NEVER invent values or specifications. If a value is not present, don't include it.
        10. Dont create empty strings or placeholder values
        11. Do not create NULL values unless absolutely necessary.
        12. Adapt the structure to the actual data presented in the datasheet rather than forcing all specifications into a single format
        13. Preserve original parameter names as much as possible, but you may normalize them if necessary for clarity
        14. Return only information that is present in the datasheet
        
        Return Valid JSON Data Only.

        Use a simple string for single-value specifications
        Example:
        {{
        "Drain-Source Voltage": "50V",
        "Gate-Source Voltage": "±20V"
        }}

        Use an object when multiple values exist
        Example:

        {{
        "Threshold Voltage": {{
        "min": "1V",
        "typ": "2V",
        "max": "3V"
        }}
        }}

        Only include fields that exist in the datasheet.
        Example:

        {{
        "Threshold Voltage": {{
        "min": "1V",
        "max": "3V"
        }}
        }}

        NOT:

        {{
        "Threshold Voltage": {{
        "min": "1V",
        "typ": "",
        "max": "3V"
        }}
        }}

        Include conditions only when provided

        Example:

        {{
        "Turn-Off Delay Time": {{
        "conditions": "VDD = 30V, ID = 0.2A, RGEN = 50Ω",
        "max": "20ns"
        }}
        }}

        Use arrays when a parameter has multiple condition rows

        Example:

        {{
        "Turn-Off Delay Time": [
        {{
        "conditions": "VDD = 30V, ID = 0.2A",
        "max": "20ns"
        }},
        {{
        "conditions": "VDD = 50V, ID = 0.5A",
        "max": "35ns"
        }}
        ]
        }}

        Required Output Structure (if a field is not CLEARLY present in the datasheet, omit it):

        {{
        "part_number": "",
        "manufacturer": "",
        "description": "",
        "specifications": {{}}
        }}

        Specifications Organization

        Group specifications according to the datasheet sections whenever possible.

        Example:

        {{
        "specifications": {{
        "absolute maximum ratings": {{
        "Drain-Source Voltage": "50V",
        "Gate-Source Voltage": "±20V"
        }},
        "electrical characteristics": {{
        "Threshold Voltage": {{
        "min": "1V",
        "typ": "2V",
        "max": "3V"
        }},
        "Turn-Off Delay Time": {{
        "conditions": "VDD = 30V, ID = 0.2A",
        "max": "20ns"
        }}
        }}
        }}
        }}

        Handling Tables

        For specification tables:

        Preserve all meaningful rows.
        Preserve test conditions.
        Preserve min/typ/max values when present.
        Preserve units.
        Combine related values into logical structures.
        Handling Missing Information

        If information is not present in the datasheet:

        Omit it when possible.
        Do not fabricate values.
        Do not create empty placeholders.
        Invalid Output Examples

        DO NOT output:

        {{
        "Drain-Source Voltage": {{
        "conditions": "",
        "min": "",
        "typ": "",
        "max": ""
        }}
        }}

        DO NOT output:

        {{
        "Threshold Voltage": {{
        "min": "1V",
        "typ": "",
        "max": "3V"
        }}
        }}

        DO NOT output:

        {{
        "parameter": null
        }}
        """

        response = client.models.generate_content(
            model = model_name,
            contents = [
                types.Part.from_bytes(data = pdf_bytes, mime_type = "application/pdf"),
                prompt
            ],
            config = types.GenerateContentConfig(
                temperature = 0,
                response_mime_type = "application/json" # forces model to output valid json data instead of regular text
            )
        )
        return json.loads(response.text)

    except Exception as e:

        if not hasattr(e, "code"):
            print(f"Error parsing PDF for {part_number} (scraper.py | line 230): {e}")
            return None

        # If model is experiencing high demand, try other models in the list
        if getattr(e, "code") == 503:
            print("Google AI model is currently experiencing high demand, could not complete request")

            model_attempt += 1
            if model_attempt < len(models):
                print(f"Trying next model: {models[model_attempt]}")
                return parse_pdf(pdf_bytes, part_number, models[model_attempt])
            else:
                print("All AI models have been tried and failed. Could not complete request.")

            return None

        # Ran out of AI tokens for current model, try next model in list
        if getattr(e, "code") == 429:
            print("Exceeded Google AI quota, could not complete request")

            model_attempt += 1
            if model_attempt < len(models):
                print(f"Trying next model: {models[model_attempt]}")
                return parse_pdf(pdf_bytes, part_number, models[model_attempt])
            else:
                print("All AI models have been tried and failed. Could not complete request.")

        print(f"Error parsing PDF for {part_number} (scraper.py | line 257): {e}")
        return None

def fetch_datasheet_url(part_number: str) -> ScrapedComponent | None:
    part_number = part_number.upper()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    # Scrape #1: DatasheetArchive. Fetch time ~3 seconds (not including PDF parsing time)
    try: 
        url = f"https://www.datasheetarchive.com/datasheet/{part_number}" # todo: add functionality for adding brand-specific searching. To update datasheetarchive url, add "/texas-instruments" to the end of the url for example
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()  # Check if the request was successful

        soup = BeautifulSoup(response.text, "html.parser")
 
        download_btn = soup.find('a', class_='download-datasheet')
        if not download_btn:
            print(f"Could not find download button for {part_number} on DatasheetArchive.")
            return None # couldnt find a download button for some reason
        
        pdf_page = download_btn['href']
        pdf_response = requests.get(pdf_page, allow_redirects=True, headers=headers, timeout=10)

        description = None
        desc = soup.find('span', class_='j-description')

        if desc:
            description = desc.getText()

        if pdf_response.headers.get('Content-Type') != 'application/pdf': # datasheet is not a pdf file
            return ScrapedComponent( 
                part_number = part_number,
                description = description,
                specifications = {},
                datasheet_url = pdf_response.url,
                source = "datasheetarchive"
            )
        
        print("Extracting data from datasheet with AI")

        ai_result = parse_pdf(pdf_response.content, part_number, models[0]) # try first model

        if not ai_result:
            print(f"AI parsing failed for {part_number}, returning empty specifications.")
            return ScrapedComponent(
                part_number = part_number,
                description = description,
                specifications = {},
                datasheet_url = pdf_response.url,
                source = "datasheetarchive"
            )

        return ScrapedComponent(
            part_number = part_number,
            description = (ai_result.get("description") or description),
            specifications = (ai_result.get("specifications") or {}),
            datasheet_url = pdf_response.url,
            source = "datasheetarchive"
        )

    except Exception as e:
        print(f"Scrape #1 (DatasheetArchive) failed for {part_number} (scraper.py | line 308): {e}")


    return None 
