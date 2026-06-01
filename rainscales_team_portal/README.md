# Rainscales GTM Intelligence Portal

A lightweight internal web portal for sales and marketing team members to self-qualify prospects.

## What it does

Team members enter a company website and get:

- ICP Score
- POC Fit Score
- Why Now
- Recommended First Use Case
- Safety Use Cases
- Operational Use Cases
- MEDDPICC Snapshot
- Stakeholders
- Discovery Questions
- POC Recommendation
- ROI Narrative
- Outreach Copy
- Objection Handling
- Downloadable HTML report

## Why hosted is better than local

Local is fine for testing. For team-wide use, deploy it so every rep uses the same version, the same scoring logic, the same API keys, and fresh web data each time.

## Local setup

```powershell
cd rainscales_team_portal
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python app.py
```

Open:

```text
http://127.0.0.1:5050
```

## Deployment

Deploy to any Python-friendly hosting service. Add these environment variables in the host dashboard:

```text
ANTHROPIC_API_KEY
FIRECRAWL_API_KEY
PORT
```

Start command:

```text
python app.py
```

## CSV batch format

```csv
Company Name,Website,Industry,Notes
Linfox,https://www.linfox.com,Logistics,Target APAC logistics operator
```
