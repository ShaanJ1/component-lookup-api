# Component Lookup API

A FastAPI REST API that finds datasheets for all major electronic components, compiles all useful data with Google AI, and returns all the important information.

### Features:
- AI powered datasheet parsing using AI
- Redis Caching + PostgreSQL Database
- Option to refresh cached components
- Fallback AI models if one fails during parsing
- Optionally skip AI for faster results using `skip_ai`  
- Pagination Support
- API key authentication for some protected endpoints
- Rate limiting  
- AI powered pdf data extraction  
- Strict input data validation  
- Detailed health information
- Swagger & Redoc documentation
- 12 total endpoints - 8 GET, 2 POST, 1 PUT, 1 DELETE

# Basic Overview

When a component gets requested, the API's follows this workflow

```text
                      Client Request
                            |
                            ⌄
                    Check Redis Cache
                            |
                            |
                -------------------------
                |                       |
                ⌄                       ⌄
          Found in Cache       Not found in Cache
                |                       |
                ⌄                       ⌄
        Return Component        Check PostgreSQL
                                        |
                            ------------------------------
                            |                            |
                            ⌄                            ⌄
                          Found                      Not Found
                            |                            |
                            ⌄                            ⌄
                      Store in Cache              Datasheet Scraper      
                            |                            |
                            ⌄                            ⌄
                    Return Component                 Download
                                                         |
                                                         ⌄
                                                AI Compiles Data
                                                         |
                                                         ⌄
                                            Store in Cache & PostgreSQL
                                                         |
                                                         ⌄
                                                 Return Component

```

After every initial fetch of a new component, the API stores the components info in a database, making future requests faster

# Tech Stack
| Category            | Technology             |
| :------------------ | :----------------------|
| API Framework       | FastAPI                |
| ASGI Server         | Uvicorn                |
| Language            | Python                 |
| Database            | PostgreSQL             |
| ORM                 | SQLAlchemy             |
| Data Validation     | Pydantic               |
| AI                  | Google Studio AI API   |
| Rate Limiter        | SlowAPI                |
| Dependency Manager  | UV                     |
| Logger              | Loguru                 |


# API Documentation
The API docs are available through:
- Swagger UI -> `/docs`
- ReDoc -> `/redocs`

# Authentication
Some endpoints require an API key, which is configured in your `.env` file.  

Here is a public demo key for the API:
```text
ZuliVuWah4pLohFCNiBI2c5E8ah6bab2
```

### Swagger
1. Open swagger docs at `/docs`
2. Click Authorize
3. Enter the demo API key

Your now authenticated to use every protected endpoint on the docs 

### HTTP Header 
```bash
X-API-KEY: DEMO_API_KEY_HERE
```

# API Endpoints:  

## Base URL:
```bash
https://component-lookup-api.hackclub.app/
```

## Public Endpoints
| Method  | Endpoint                                   | Description  |
| :-----: | :----------------------------------------- | :----------- |
|   GET   | `/`                                        | The root endpoint |
|   GET   | `/docs`                                    | The Swagger documentation for this API |
|   GET   | `/redocs`                                  | The Redoc documentation for this API |
|   GET   | `/health`                                  | View the API's status and metrics |
|   GET   | `/components`                              | Browse through the components saved in the API's database |
|   GET   | `/components/{part_number}`                | Fetch/retrieve a component's information |
|  POST   | `/components/updatespecs/{part_number}`    | Regenerate AI specifications for a component |

### Optional Query Parameters
| Method  | Endpoint                      | Parameter      | Description  |
| :-----: | :---------------------------- | -------------- | :----------- |
|   GET   | `/components/`                | `page`         | Specify what page to view |
|   GET   | `/components/`                | `page_size`    | Specify how many components to display per page |
|   GET   | `/components/{part_number}`   | `manufacturer` | Filter component info by manufacturer |
|   GET   | `/components/{part_number}`   | `skip_ai`      | Skip AI parsing and return basic information about the component (no specifications table)|
|   GET   | `/components/{part_number}`   | `force_fetch`  | Ignore database and fetch the component from scratch again |

<details>
<summary><strong>Supported Manufacturers</strong></summary>  

`Texas-Instruments`   
`Central-Semiconductor`  
`GigaDevice-Semiconductor-(Beijing)-Inc`  
`SLKOR`  
`2Pai-Semiconductor`  
`3peak-Incorporated`  
`Shanghai-Awinic-Technology`  
`Murata-Manufacturing-Co-Ltd`  
`Amphenol-Positronic`  
`Microchip-Technology-Inc`  
`Littelfuse-Inc`  
`Phoenix-Contact`  
`ROHM-Semiconductor`  
`onsemi`  
`STMicroelectronics`  
`Analog-Devices`  
`Advantech-Co-Ltd`  
`Toshiba-America-Electronic-Components`  
`Same-Sky`  
`NXP-Semiconductors`  
`Allegro-MicroSystems-LLC`  
`Renesas`  
`SG-Micro`  
`Broadcom`  
`KEMET-Corporation`  
`Vishay`  
`Apex-Microtechnology-Inc`  
`Nisshinbo-Micro-Devices`  
`YAGEO-Corporation`  
`Wima`  
`Rubycon-Corporation`  
`Infineon`  
`Honeywell`  
`HARTING-Elektronik`  
`Coilcraft`  
`3M`  
`WAGO-Innovative-Connections`  
`ECS-Inc-International`  
`Abracon-Corporation`  
`Cirrus-Logic`  
`Bourns-Inc`  
`Molex`  
`Omron`  
`EDAC-Inc`  
`Advanced-Power-Technologies`  
`KEC`  
`Kingbright`  
`SanRex`  
`Seiko-Instruments-Inc`  
`Kyocera-AVX-Components`  
`Integrated-Silicon-Solution-Inc`  
`Stellar-Technology-Inc`  
`Holtek-Semiconductor-Inc`  
`Telemechanique-Sensors`  
`HPMicro-Semiconductor-Co-Ltd`  
`XINGLIGHT`  
`Microdiode-Semiconductor`  
`Geehy-Semiconductor`  
`Shikues-Semiconductor`  
`NEC`  
`Semikron`  
`Dialight`  
`TE-Connectivity`  
`Mini--Circuits`  
`Vicor`  
`Keystone-Electronics`  
`Quanzhou-KTsense-Microelectronics-Co..Ltd`  
`RUNIC`  
`Intel`  
`MCC`  
`Fujitsu`  
`EIC-Semiconductor`  
`Altera`  
`Agilent-Technologies`  
`Advanced-Micro-Devices`  
`Wurth-Elektronik`  


> This list of manufacturers was compiled from the datasheet provider, most of them should work, but some may fail because of inconsistencies with the provider's system.
</details>


## Protected Endpoints

| Method  | Endpoint                                   | Description  |
| :-----: | :----------------------------------------- | :----------- |
|   PUT   | `/components/{part_number}`                | Manually edit a component in our database |
|  DELETE | `/components/{part_number}`                | Delete a component in our database |
|  POST   | `/components/fillmissingspecs`             | Retry the AI parser for all components in the database with missing specifications |
|   GET   | `/components/viewsaves`                    | View the version history for all components |
|   GET   | `/components/viewsaves/{part_number}`      | View the version history for a specific component |

# AI Processing
If a requested component is not already cached:

1. The API searches through its datasheet sources
2. The PDF of the datasheet is saved
3. The AI extracts all important specifications from it, returning a JSON object
4. The results are stored in our database
5. Future results for that component will come directly from the cache/database

To improve the reliability of the AI, the API automatically retries parsing attempts using multiple AI models in the case of a model failing. 

### Limitations
- Currently the API only scrapes datasheets from DatasheetArchive, as most of the other datasheet providers strictly enforce anti-bot/anti-scraping processes
- The current AI being used is the Google AI Studio API on the free tier, so it often hits its usage limits and has to deal with longer wait times, and because of this increased fail rate, I added 2 other fallback AI models
- New components may take from 20-120 seconds to process and fetch, depending on AI availability, however with the `skip_ai` parameter enabled, it may take as little as 5 seconds to fetch a brand new component.
- Some older or more uncommon components may not be available on our datasheet sources.
- If all AI reattempts fail, an empty specifications table and a generic description will be returned.
- AI parsing only supports PDF Datasheets
> Since the specifications table is completely made from AI, always be cautious when working with important values. There may be small issues with some datasheets such as PDFs with only images and no text.

## HTTP Responses
Here are the error responses the API may produce.
| Status                      | Likely Cause              |
| :-------------------------- | :-------------------------|
| 400 Bad Request             | The request is malformed |
| 401 Unauthorized            | Your API key is missing or invalid |
| 404 Not Found               | The requested component could not be found |
| 409 Conflict                | The database faced an error while trying to save data, please try again |
| 422 Unprocessable Entity    | Request is valid but one of your parameters have invalid values |
| 429 Too Many Requests       | You have exceeded the rate limit for an endpoint, please try again later |
| 500 Internal Server Error   | An unexpected error occured on the API's server, please try again |
| 502 Bad Gateway             | Our datasheet provider returned us a 500 error when fetching a component, please try again later |
| 503 Service Unavailable     | The AI's limit has been reached, please try again later or use the `skip_ai` parameter if fetching a component |
| 504 Gateway Timeout         | Race condition handling timed out, please try again |


# Example Requests
### 1.

```bash
curl "https://component-lookup-api.hackclub.app/components/NE555"
```

Response:

```json
{
  "part_number": "NE555",
  "description": "Precision Timer IC",
  "specifications": {
    "Supply Voltage": "4.5V - 16V",
    "Operating Temperature": "-55°C to +125°C",
    "Package": "DIP-8"
  },
  "datasheet_url": "https://...",
  "source": "datasheetarchive",
  "created_at": "2026-06-29T06:29:13.830923Z",
  "updated_at": "2026-06-29T06:29:13.830923Z"
}

```

---

### 2.

```bash
curl "https://component-lookup-api.hackclub.app/components/STM32F103C8T6?skip_ai=True&manufacturer=STMicroelectronics"
```

Response:

```json
{
  "part_number": "STM32F103C8T6",
  "description": "Embedded - Microcontrollers, Integrated Circuits (ICs), MCU ARM 64KB FLASH MEM 48-LQFP",
  "specifications": {},
  "datasheet_url": "https://...",
  "source": "datasheetarchive",
  "created_at": "2026-06-29T06:29:13.830923Z",
  "updated_at": "2026-06-29T06:29:13.830923Z"
}
```

# Installation

## Clone the repository
```bash
git clone https://github.com/ShaanJ1/component-lookup-api/

cd component-lookup-api
```

## Install UV and Redis

- UV is used as the package manager for this project, install it [`here`](https://docs.astral.sh/uv/getting-started/installation/)  
- Redis is used as the cache for this project, install it [`here`](https://redis.io/docs/latest/operate/oss_and_stack/install/archive/install-redis/)  

## Install dependencies

```bash
uv sync
```

## Add environment variables
Create a `.env` file in the project root with the following:

```bash
DATABASE_URL=
GOOGLE_API_KEY=
API_KEY=
ENVIRONMENT=LOCAL
```
> Keep ENVIRONMENT=LOCAL unless your deploying the API on an external server

## Run the API

```bash
uv run main.py
```

Now the API should be running on `http://127.0.0.1:8000/`