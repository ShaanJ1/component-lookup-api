# Scraper for finding datasheet urls from external resources if not already in the database 
# Currently only scrapes from datasheet archive since most other sites have strict bot protection and I was unable to find alternatives

# Uses Google AI to parse PDF datasheets and extract specifications

import os
import time
from click import prompt
import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel

from datetime import datetime, timedelta, timezone

from typing import Any
import json

from dotenv import load_dotenv

from google import genai
from google.genai import types

from cache import redis_client

from loguru import logger

load_dotenv()

google_api_key = os.getenv("GOOGLE_API_KEY")

if not google_api_key:
    logger.critical("GOOGLE_API_KEY environment variable is not set.")

client = genai.Client(
    api_key = google_api_key
)

models = ['gemini-3.5-flash', 'gemini-3-flash-preview', 'gemini-2.5-flash'] # try these models in order if one fails

model_limits = {
    "per_minute": 5,
    "per_day": 20
}

class ScrapedComponent(BaseModel):
    part_number: str
    description: str | None
    specifications: dict[str, Any] | None
    datasheet_url: str
    source: str

@logger.catch(reraise=False)
def check_rate_limit(model: str):
    minute_key = f"minute_ai_ratelimit:{model}"
    daily_key = f"daily_ai_ratelimit:{model}"

    now = datetime.now(timezone.utc)
    tmr = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    minute_count = redis_client.incr(minute_key)
    daily_count = redis_client.incr(daily_key)

    if minute_count == 1:
        redis_client.expire(minute_key, 60)  # Set expiration for 1 minute

    if daily_count == 1:
        redis_client.expire(daily_key, int((tmr - now).total_seconds())) # expire at midnight UTC

    #checking minute limit
    if minute_count > model_limits["per_minute"]:
        logger.warning(f"AI Minute Rate Limit exceeded for model {model}.")
        redis_client.decr(minute_key)
        redis_client.decr(daily_key)

        return "MINUTE_LIMIT"
    
    #checking daily limit
    if daily_count > model_limits["per_day"]:
        logger.warning(f"AI Daily Rate Limit exceeded for model {model}.")
        redis_client.decr(minute_key)
        redis_client.decr(daily_key)

        return "DAILY_LIMIT"
    
    logger.debug(f"AI Rate Limit check passed for model {model}. Minute Count: {minute_count}, Daily Count: {daily_count}")
    return None

# extract component specifications from a pdf datasheet
@logger.catch(reraise=False)
def parse_pdf(pdf_bytes: bytes, part_number: str) -> dict | None:  # fetch time ~20-120 seconds (depending on model and app latency)
    """Parses a PDF datasheet using AI and extracts all relevant data for a specific component. Returns None if all attempts failed."""
    logger.info(f"Initalizing PDF AI parsing for: {part_number}")
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
    15. Include pinout information at the start of the specifications object if PRESENT in the datasheet, otherwise omit
    16. Include the available package types at the start of the specifications object if PRESENT in the datasheet, otherwise omit. It's better to omit true information than to fabricate it.
    
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
    "specifications": {{}},
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

    for model_attempt in models:
        try:
            ratelimited = check_rate_limit(model_attempt)
            if ratelimited in ("MINUTE_LIMIT", "DAILY_LIMIT"):
                return {
                    "RATELIMIT_EXCEEDED": True,
                    "TYPE": ratelimited,
                    "MODEL": model_attempt
                }

            logger.debug(f"Attempting to parse PDF for {part_number} with AI model: {model_attempt}")
            response = client.models.generate_content(
                model = model_attempt,
                contents = [
                    types.Part.from_bytes(data = pdf_bytes, mime_type = "application/pdf"),
                    prompt
                ],
                config = types.GenerateContentConfig(
                    temperature = 0,
                    response_mime_type = "application/json" # forces model to output valid json data instead of regular text
                )
            )

            try:
                data = json.loads(response.text)
                logger.success(f"Successfully parsed PDF for {part_number} with AI model: {model_attempt}. Data: {data}")
                return data
            except json.JSONDecodeError as e:
                logger.exception(f"AI Model {model_attempt} returned invalid JSON: {e}")
                return None
        
        except Exception as e: # todo: sometimes this throws an error without trying all models
            response_code = getattr(e, "code", None)
            logger.error(f"Error parsing PDF for {part_number} with AI model {model_attempt} (code: {response_code}): {e}")
            if response_code == 400:
                logger.error(f"AI returned an INVALID_ARGUMENT error. Error: {e}")
                return None
            

            if response_code not in (503, 429): # If the errors are not because of high demand or exceeded quota
                logger.error(f"AI Model recieved an unexpected non retryable error: {e}")
                return None # Server sided error that isnt what we expected, quit operation
            
            logger.warning(f"AI Model {model_attempt} failed, retrying with fallback model in 1 second")
            time.sleep(1) 

    logger.error(f"All AI model attempts failed for {part_number}. Unable to parse PDF.")
    return None

@logger.catch(reraise=False)
def fetch_datasheet_url(part_number: str, manufacturer: str | None = None, skip_ai: bool | str = False) -> ScrapedComponent | dict[str, Any] | None | int:
    """Fetch the datasheet URL and all other relevant info for a specific component by scraping external resources."""
    part_number = part_number.upper()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    # Scrape #1: DatasheetArchive. Fetch time ~3 seconds (not including PDF parsing time)
    try: 
        mfg = f"/{manufacturer.lower()}" if manufacturer else ""
        url = f"https://www.datasheetarchive.com/datasheet/{part_number}{mfg}"
        logger.debug(f"Fetching from DatasheetArchive for {part_number} with URL: {url}")

        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()  # Check if the request was successful

        soup = BeautifulSoup(response.text, "html.parser")
 
        download_btn = soup.find('a', class_='download-datasheet')
        if not download_btn:
            logger.warning(f"Could not find download button for {part_number} on DatasheetArchive.")
            return None # couldnt find a download button for some reason
        
        pdf_page = download_btn['href']
        pdf_response = requests.get(pdf_page, allow_redirects=True, headers=headers, timeout=10)

        description = ""
        desc = soup.find('span', class_='j-description')
        
        if desc:
            description = desc.getText()

        if pdf_response.headers.get('Content-Type') != 'application/pdf': # datasheet is not a pdf file
            logger.warning(f"Datasheet for {part_number} is not a PDF. Content-Type: {pdf_response.headers.get('Content-Type')}")
            return ScrapedComponent( 
                part_number = part_number,
                description = description,
                specifications = {},
                datasheet_url = pdf_response.url,
                source = "datasheetarchive"
            )
        
        if skip_ai: # User sent a request to skip the AI parsing of datasheet
            logger.info(f"Skipping AI parsing for {part_number} as requested.")
            return ScrapedComponent(
                part_number = part_number,
                description = description,
                specifications = {},
                datasheet_url = pdf_response.url,
                source = "datasheetarchive"
            )

        
        logger.info("Sending datasheet to AI Parser...")
        ai_result = parse_pdf(pdf_response.content, part_number)

        if not ai_result:
            logger.warning(f"AI parsing failed for {part_number}, returning empty specifications.")
            return ScrapedComponent(
                part_number = part_number,
                description = description,
                specifications = {},
                datasheet_url = pdf_response.url,
                source = "datasheetarchive"
            )

        if "RATELIMIT_EXCEEDED" in ai_result:
            return {
                "RATELIMIT_EXCEEDED": True,
                "component": ScrapedComponent(
                    part_number = part_number,
                    description = description,
                    specifications = {},
                    datasheet_url = pdf_response.url,
                    source = "datasheetarchive"
                ),
                "TYPE": ai_result.get("TYPE"),
                "MODEL": ai_result.get("MODEL")
            }

        return ScrapedComponent(
            part_number = part_number,
            description = (ai_result.get("description") or description),
            specifications = (ai_result.get("specifications") or {}),
            datasheet_url = pdf_response.url,
            source = "datasheetarchive"
        )

    except requests.exceptions.HTTPError as http_err:
        if http_err.response.status_code == 500:
            logger.error(f"DatasheetArchive returned a 500 error for {part_number}")
            return 500 
        logger.exception(f"HTTP error occurred while fetching datasheet for {part_number}: {http_err}")

    except Exception as e:
        logger.exception(f"Scrape #1 (DatasheetArchive) failed entirely for {part_number}: {e}")

    return None 
