# Fincap

Real-time company financial summary powered by **DART** (Korea) and **SEC EDGAR** (US & Global).

## Features

- 🔍 Search by company name, Korean stock code, or US ticker
- 🇰🇷 Korean companies via **DART OpenAPI** (FSS)
- 🇺🇸 US & global companies via **SEC EDGAR XBRL**
- 💵 All figures normalized to **USD**
- 📊 Revenue, Operating Income, Net Income, Total Assets, Debt Ratio
- 🌍 Revenue by Geography (when available)
- 🔗 Direct link to original filings

## Quick Start

```bash
pip install -r requirements.txt

# Set API keys
cp .env.example .env
# Edit .env with your DART API key

streamlit run app.py
```

## Environment Variables

```env
DART_API_KEY=your_dart_api_key_here   # Get free at opendart.fss.or.kr
SEC_USER_AGENT=YourApp contact@email.com  # Required by SEC (no key needed)
```

DART API key: https://opendart.fss.or.kr/uat/uia/egovLoginUsr.do (free)

## Tech Stack

- [Streamlit](https://streamlit.io) — UI
- [DART OpenAPI](https://opendart.fss.or.kr) — Korean filings
- [SEC EDGAR](https://www.sec.gov/developer) — US filings (free, no key)
