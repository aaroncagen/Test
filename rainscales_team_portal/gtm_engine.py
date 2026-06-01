import csv
import html
import json
import os
import re
import time
from dataclasses import dataclass, asdict
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

try:
    from anthropic import Anthropic
except Exception:
    Anthropic = None

ROOT = Path(__file__).parent
REPORTS = ROOT / "reports"
REPORTS.mkdir(exist_ok=True)

@dataclass
class ProspectReport:
    company_name: str
    website: str
    industry: str
    description: str
    icp_score: int
    poc_fit_score: int
    tier: str
    why_now: str
    first_use_case: str
    safety_use_cases: List[str]
    operations_use_cases: List[str]
    stakeholders: List[str]
    discovery_questions: List[str]
    poc_recommendation: str
    roi_narrative: str
    outreach_email: str
    linkedin_message: str
    assumptions: List[str]
    report_file: str


def slugify(value: str) -> str:
    value = re.sub(r"https?://", "", value.lower()).strip("/")
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "prospect"


def fetch_with_firecrawl(url: str) -> Optional[str]:
    key = os.getenv("FIRECRAWL_API_KEY")
    if not key:
        return None
    endpoint = "https://api.firecrawl.dev/v1/scrape"
    payload = {
        "url": url,
        "formats": ["markdown", "html"],
        "onlyMainContent": False,
        "waitFor": 2000,
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        r = requests.post(endpoint, headers=headers, json=payload, timeout=60)
        r.raise_for_status()
        data = r.json().get("data", {})
        return data.get("markdown") or data.get("html") or ""
    except Exception:
        return None


def fetch_basic(url: str) -> str:
    headers = {"User-Agent": "Mozilla/5.0 RainscalesGTMPortal/1.0"}
    r = requests.get(url, headers=headers, timeout=25)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    meta_desc = ""
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        meta_desc = meta["content"]
    text = soup.get_text(" ", strip=True)
    return f"Title: {title}\nMeta description: {meta_desc}\n\n{text[:25000]}"


def fetch_site(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    live = fetch_with_firecrawl(url)
    if live:
        return live[:30000]
    return fetch_basic(url)[:30000]


def heuristic_report(url: str, content: str, company_hint: str = "") -> Dict:
    lower = content.lower()
    company = company_hint or extract_company_name(url, content)
    industry = "Industrial / Operations"
    score = 45
    poc = 40

    signals = {
        "logistics": ["logistics", "warehouse", "distribution", "freight", "fleet", "transport", "supply chain", "3pl"],
        "manufacturing": ["manufacturing", "plant", "factory", "production", "assembly"],
        "energy": ["oil", "gas", "energy", "utility", "refinery", "pipeline"],
        "healthcare": ["hospital", "healthcare", "clinic", "patient", "medical center"],
        "safety": ["safety", "ehs", "hse", "osha", "iso 45001", "zero harm", "vision zero", "whs"],
        "cameras": ["cctv", "camera", "video surveillance", "monitoring"],
        "multisite": ["locations", "facilities", "sites", "global", "nationwide", "warehouses", "distribution centers", "distribution centres"],
    }

    hits = {k: sum(1 for w in words if w in lower) for k, words in signals.items()}
    if hits["logistics"]:
        industry = "Logistics & Distribution"; score += 25
    elif hits["manufacturing"]:
        industry = "Manufacturing"; score += 20
    elif hits["energy"]:
        industry = "Energy / Utilities"; score += 20
    elif hits["healthcare"]:
        industry = "Healthcare Operations"; score += 15

    score += min(hits["safety"] * 4, 20)
    score += min(hits["multisite"] * 3, 15)
    score += min(hits["cameras"] * 5, 10)
    poc += min(hits["safety"] * 5, 20) + min(hits["cameras"] * 10, 20) + min(hits["multisite"] * 4, 15)
    score = max(0, min(95, score))
    poc = max(0, min(90, poc))

    tier = "Tier 1 — Strong ICP Match" if score >= 80 else "Tier 2 — Good Fit" if score >= 65 else "Tier 3 — Nurture" if score >= 45 else "Tier 4 — Deprioritize"

    return {
        "company_name": company,
        "website": url,
        "industry": industry,
        "description": summarize_description(content, company),
        "icp_score": score,
        "poc_fit_score": poc,
        "tier": tier,
        "why_now": "The account shows public signals of operational complexity, safety exposure, and potential multi-site standardization. Validate current safety visibility, camera infrastructure, and active initiatives during discovery.",
        "first_use_case": "Forklift/Pedestrian Interaction or High-Risk Zone Monitoring",
        "safety_use_cases": ["Forklift and pedestrian proximity detection", "PPE compliance monitoring", "Restricted/high-risk zone alerts"],
        "operations_use_cases": ["Loading dock throughput visibility", "Dwell time and congestion analytics", "Process compliance verification"],
        "stakeholders": ["VP/Director of EHS", "VP Operations / Site Operations Leader", "IT / Security Infrastructure Owner"],
        "discovery_questions": [
            "What safety events or near misses are hardest to see before they become incidents?",
            "Where do forklifts, pedestrians, trucks, or contractors interact most often?",
            "Do you already have CCTV coverage in the areas you would want monitored?",
            "What baseline metrics would determine whether a POC is successful?",
            "Who owns the decision if the pilot proves measurable value?",
        ],
        "poc_recommendation": "Run a 60–90 day pilot at one high-traffic site using existing CCTV where possible. Focus on one safety use case and one operational use case with weekly reporting.",
        "roi_narrative": "Estimated value should be framed around reduced incidents, faster response, less manual audit time, and improved operational visibility. Validate baselines before presenting financial ROI.",
        "outreach_email": f"Hi [Name],\n\nI was looking at {company} and noticed signals that suggest safety and operational visibility may be difficult to standardize across sites.\n\nRainscales helps teams use existing CCTV to detect high-risk behaviors and operational bottlenecks in real time.\n\nWould it be worth a short conversation to compare what you can see today versus what leadership wants measured?\n\nBest,\n[Your Name]",
        "linkedin_message": f"Hi [Name] — I came across {company} and thought Rainscales may be relevant if your team is looking to improve safety visibility or operational monitoring across sites. Open to connecting?",
        "assumptions": ["Existing CCTV infrastructure must be validated.", "ROI estimates require confirmed baselines.", "Stakeholder titles should be verified in Sales Navigator or CRM."],
    }


def extract_company_name(url: str, content: str) -> str:
    m = re.search(r"Title:\s*([^\n|—-]+)", content)
    if m and len(m.group(1).strip()) > 2:
        return m.group(1).strip()[:60]
    host = re.sub(r"https?://", "", url).split("/")[0].replace("www.", "")
    return host.split(".")[0].title()


def summarize_description(content: str, company: str) -> str:
    text = re.sub(r"\s+", " ", content).strip()
    return (text[:280] + "...") if len(text) > 280 else text


def ai_report(url: str, content: str, company_hint: str = "") -> Dict:
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key or Anthropic is None:
        return heuristic_report(url, content, company_hint)
    client = Anthropic(api_key=key)
    prompt = f"""
You are the Rainscales GTM Intelligence engine. Analyze this company website for Rainscales, an intelligent detection platform using existing CCTV/sensors for safety and operations in industrial environments.

Return ONLY valid JSON with these exact keys:
company_name, website, industry, description, icp_score, poc_fit_score, tier, why_now, first_use_case, safety_use_cases, operations_use_cases, stakeholders, discovery_questions, poc_recommendation, roi_narrative, outreach_email, linkedin_message, assumptions.

Rules:
- Do not invent facts. Put unknowns into assumptions.
- Score ICP 0-100 based on industry fit, safety complexity, operational complexity, existing CCTV likelihood, multi-site potential, POC readiness.
- Score POC fit separately.
- Keep lists to 3-5 items.
- Keep copy field-ready for sales reps.

URL: {url}
Company hint: {company_hint}
Website content:
{content[:24000]}
"""
    try:
        msg = client.messages.create(
            model="claude-3-5-sonnet-latest",
            max_tokens=4500,
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        text = re.sub(r"^```json|```$", "", text, flags=re.MULTILINE).strip()
        data = json.loads(text)
        # Ensure required fields
        fallback = heuristic_report(url, content, company_hint)
        fallback.update({k: data.get(k, fallback[k]) for k in fallback.keys() if k in data})
        return fallback
    except Exception as e:
        data = heuristic_report(url, content, company_hint)
        data["assumptions"].append(f"AI generation failed; heuristic fallback used: {str(e)[:120]}")
        return data


def render_report(data: Dict) -> str:
    slug = slugify(data.get("company_name") or data.get("website"))
    filename = f"{slug}-qualification-report.html"
    path = REPORTS / filename

    def list_items(items):
        return "".join(f"<li>{html.escape(str(x))}</li>" for x in (items or []))
    def cards(items):
        return "".join(f'<div class="card"><p>{html.escape(str(x))}</p></div>' for x in (items or []))

    score = int(data.get("icp_score", 0))
    poc = int(data.get("poc_fit_score", 0))
    tier_class = "tier1" if score >= 80 else "tier2" if score >= 65 else "tier3" if score >= 45 else "tier4"

    html_doc = f"""<!doctype html>
<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{html.escape(data['company_name'])} — Rainscales Qualification Report</title>
<link rel='stylesheet' href='/static/styles.css'></head>
<body><main class='wrap'>
<header class='hero'>
<div><div class='eyebrow'>Rainscales GTM Intelligence</div><h1>{html.escape(data['company_name'])}</h1><a href='{html.escape(data['website'])}'>{html.escape(data['website'])}</a><p>{html.escape(data['description'])}</p></div>
<div class='score {tier_class}'><span>{score}</span><small>ICP Score</small><em>{html.escape(data['tier'])}</em></div>
<div class='score poc'><span>{poc}</span><small>POC Fit</small><em>Validate assumptions</em></div>
</header>
<section><h2>Why Now</h2><p>{html.escape(data['why_now'])}</p></section>
<section><h2>Recommended First Use Case</h2><div class='highlight'>{html.escape(data['first_use_case'])}</div></section>
<section class='grid'><div><h2>Safety Use Cases</h2>{cards(data['safety_use_cases'])}</div><div><h2>Operational Use Cases</h2>{cards(data['operations_use_cases'])}</div></section>
<section class='grid'><div><h2>Stakeholders</h2><ul>{list_items(data['stakeholders'])}</ul></div><div><h2>Discovery Questions</h2><ul>{list_items(data['discovery_questions'])}</ul></div></section>
<section><h2>POC Recommendation</h2><p>{html.escape(data['poc_recommendation'])}</p></section>
<section><h2>ROI Narrative</h2><p>{html.escape(data['roi_narrative'])}</p></section>
<section class='grid'><div><h2>Email</h2><pre>{html.escape(data['outreach_email'])}</pre></div><div><h2>LinkedIn</h2><pre>{html.escape(data['linkedin_message'])}</pre></div></section>
<section><h2>Assumptions to Validate</h2><ul>{list_items(data['assumptions'])}</ul></section>
<footer>Generated {date.today().isoformat()} · Rainscales Prospect Qualification Portal</footer>
</main></body></html>"""
    path.write_text(html_doc, encoding="utf-8")
    return filename


def analyze(url: str, company_hint: str = "") -> ProspectReport:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    content = fetch_site(url)
    data = ai_report(url, content, company_hint)
    data["website"] = url
    report_file = render_report(data)
    data["report_file"] = report_file
    return ProspectReport(**data)


def batch_analyze(csv_path: Path) -> List[ProspectReport]:
    results = []
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            website = row.get("Website") or row.get("website") or row.get("URL") or row.get("url")
            company = row.get("Company Name") or row.get("Company") or row.get("company") or ""
            if website:
                results.append(analyze(website, company))
                time.sleep(0.5)
    summary = REPORTS / "batch-summary.csv"
    with summary.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["company_name", "website", "industry", "icp_score", "poc_fit_score", "tier", "first_use_case", "report_file"])
        writer.writeheader()
        for r in results:
            d = asdict(r)
            writer.writerow({k: d.get(k, "") for k in writer.fieldnames})
    return results
