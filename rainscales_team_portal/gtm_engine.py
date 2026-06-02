import csv
import html
import json
import os
import re
import time
from dataclasses import dataclass, asdict, field
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

# ── ICP Profile (from Rainscales_ICP_Profile.pptx) ────────────────────────────
ICP_PROFILE = """
RAINSCALES ICP PROFILE — use this to score and qualify every prospect.

PRIMARY PERSONA:
- Title: VP/Director of Operations OR Head of EHS/Safety & Risk
- Seniority: Director to C-Level (COO, VP Ops, Head of Safety)
- Company Size: 150–2,500 employees
- Revenue: $50M–$1B
- Industries: Warehouse & Logistics, Manufacturing, Oil & Gas, Healthcare Facilities, Construction
- Geography: North America + Southeast Asia (multi-site ops, labor variability)

TOP FEARS (quote back in outreach):
1. "Something bad is going to happen on my watch and I won't see it coming."
2. "We're sitting on risk, but I can't prove it until it's too late."
3. "We're spending on safety, but I can't tie it to real outcomes."
4. "My team is stretched thin and missing things we shouldn't."
5. "If an audit or incident happens, I won't have defensible data."

TOP DESIRES:
1. Real visibility across every site without hiring more people
2. Prove ROI on safety and operations improvements
3. Fewer incidents without slowing down operations
4. Works with existing camera infrastructure
5. Scale best practices across locations consistently

TRIGGER EVENTS (Why Now signals to look for):
- Serious safety incident or near-miss in their industry or at their company
- Failed audit or compliance pressure (OSHA, ISO 45001, WHS Act, etc.)
- Rapid expansion — new sites or geographies
- Leadership pressure to reduce costs or improve KPIs
- Prior technology solution failure

DISQUALIFIERS (lower score if present):
- Fewer than 100 employees
- Pure IT/security buyer with no ops ownership
- No existing camera or sensor infrastructure mentioned
- Innovation team without budget authority
- Heavily regulated org with multi-year procurement cycles

LANGUAGE TO USE IN OUTREACH:
"Real visibility across sites" / "reactive to proactive" / "scale with what you already have" /
"can't prove improvement" / "understaffed for this" / "flying blind in certain areas"
"""


@dataclass
class ProspectReport:
    company_name: str
    website: str
    industry: str
    description: str
    icp_score: int
    poc_fit_score: int
    tier: str
    company_evidence: List[str]
    evidence_limited: bool
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


# ── Web fetching ──────────────────────────────────────────────────────────────

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


# ── External intelligence gathering ───────────────────────────────────────────

def ddg_search(query: str, max_results: int = 5) -> List[Dict]:
    """DuckDuckGo HTML search — no API key needed. Returns list of {title, url, snippet}."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; RainscalesGTM/1.0)"}
        r = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query, "kl": "us-en"},
            headers=headers,
            timeout=15,
        )
        soup = BeautifulSoup(r.text, "html.parser")
        results = []
        for res in soup.select(".result")[:max_results]:
            title_el = res.select_one(".result__a")
            snip_el  = res.select_one(".result__snippet")
            url_el   = res.select_one(".result__url")
            if not title_el:
                continue
            results.append({
                "title":   title_el.get_text(" ", strip=True),
                "url":     url_el.get_text(" ", strip=True).strip() if url_el else "",
                "snippet": snip_el.get_text(" ", strip=True) if snip_el else "",
            })
        return results
    except Exception:
        return []


def _fetch_page_brief(raw_url: str, max_chars: int = 2500) -> str:
    """Fetch one external page and return clean text. Silent on error."""
    try:
        url = raw_url if raw_url.startswith("http") else "https://" + raw_url.lstrip("/")
        headers = {"User-Agent": "Mozilla/5.0 (compatible; RainscalesGTM/1.0)"}
        r = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "nav", "footer", "aside"]):
            tag.decompose()
        return soup.get_text(" ", strip=True)[:max_chars]
    except Exception:
        return ""


def gather_intelligence(url: str, company_name: str) -> str:
    """
    Gather buying signals from sources beyond the company's own website.

    Searches (all via DuckDuckGo, no extra API keys required):
      1. Safety incidents / OSHA / regulatory violations
      2. Expansion & growth signals (new sites, hiring, acquisitions)
      3. Reddit mentions — employee and industry discussion (page fetched)
      4. Job postings — tech stack, org structure, open pain points (page fetched)
      5. Review sites — G2, Capterra, Glassdoor (current tools + satisfaction)
      6. News & press releases

    For Reddit and job postings the top result page is also fetched for richer signal.
    Total output capped at ~14,000 chars to stay within the AI context budget.
    """
    if not company_name or company_name.lower() in ("unknown", "prospect", ""):
        company_name = (
            re.sub(r"https?://(?:www\.)?", "", url)
            .split(".")[0]
            .replace("-", " ")
            .title()
        )
    name = company_name.strip().strip("\"'")
    NL = "\n"
    sections: List[str] = []

    def _run(label: str, query: str, fetch_urls: int = 0,
             skip_domains: Optional[List[str]] = None) -> None:
        results = ddg_search(query, max_results=5)
        if not results:
            return
        block = [NL + "=== " + label + " ==="]
        fetched = 0
        for res in results:
            line = "* " + res["title"]
            if res["snippet"]:
                line += ": " + res["snippet"]
            block.append(line)
            if fetch_urls > 0 and fetched < fetch_urls and res["url"]:
                skip = skip_domains or []
                if not any(s in res["url"].lower() for s in skip):
                    text = _fetch_page_brief(res["url"], max_chars=2000)
                    if len(text) > 200:
                        block.append("  [excerpt] " + text[:1800])
                    fetched += 1
        sections.append(NL.join(block))
        time.sleep(0.4)

    # 1. Safety / OSHA / regulatory incidents
    _run(
        "Safety Incidents & Regulatory Signals",
        '"' + name + '" OSHA OR "safety incident" OR "workplace accident" OR "safety violation" OR "workers compensation"',
    )

    # 2. Expansion & growth
    _run(
        "Growth & Expansion Signals",
        '"' + name + '" "new facility" OR expanding OR acquisition OR "new warehouse" OR "new distribution center" OR opened 2023 2024 2025',
    )

    # 3. Reddit — candid employee / customer / industry discussion
    _run(
        "Reddit Discussion",
        '"' + name + '" site:reddit.com',
        fetch_urls=1,
        skip_domains=["ads.", "preview."],
    )

    # 4. Job postings — tech stack, org structure, open pain points
    _run(
        "Job Postings (Tech & Org Signals)",
        '"' + name + '" (safety manager OR EHS OR "operations manager" OR "continuous improvement") site:indeed.com OR site:linkedin.com/jobs',
        fetch_urls=1,
        skip_domains=["ads."],
    )

    # 5. Review sites — current tech stack and satisfaction signals
    _run(
        "Reviews & Technology Stack",
        '"' + name + '" site:g2.com OR site:capterra.com OR site:glassdoor.com OR site:comparably.com',
        fetch_urls=1,
    )

    # 6. Industry news & press releases
    _run(
        "News & Press Releases",
        '"' + name + '" announcement OR "press release" OR award OR contract OR partnership 2024 2025',
    )

    combined = NL.join(sections).strip()
    return combined[:14000] if combined else ""




# ── Evidence extraction ────────────────────────────────────────────────────────

def extract_company_evidence(url: str, content: str, client) -> tuple[List[str], bool]:
    """
    Step 1 of analysis: extract 5-8 specific facts directly stated on the website.
    Returns (evidence_list, evidence_limited).
    evidence_limited = True if content is too thin for reliable recommendations.
    """
    word_count = len(content.split())
    if word_count < 200:
        return [f"Very limited content available ({word_count} words scraped from {url})"], True

    prompt = f"""Extract 5-8 specific, verifiable facts from this company website content.

Rules:
- Only include facts DIRECTLY STATED on the website — no inferences, no assumptions
- Make each fact specific: include numbers, certifications, location names, product names, team names where present
- Focus on: industry/operations type, scale (employees, sites, revenue), safety programs or certifications, technology mentions, operational complexity, geographic footprint, recent news or expansion
- If the content is too thin to find 5 specific facts, return what you can and set "evidence_limited": true

Return ONLY valid JSON in this exact format:
{{
  "evidence": ["fact 1", "fact 2", ...],
  "evidence_limited": true/false,
  "word_estimate": 500
}}

Website URL: {url}
Content:
{content[:20000]}"""

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        text = re.sub(r"^```json|```$", "", text, flags=re.MULTILINE).strip()
        parsed = json.loads(text)
        evidence = parsed.get("evidence", [])
        limited = parsed.get("evidence_limited", False) or len(evidence) < 3
        return evidence, limited
    except Exception as e:
        # Fall back to basic keyword extraction
        return _extract_evidence_heuristic(url, content), word_count < 500


def _extract_evidence_heuristic(url: str, content: str) -> List[str]:
    """Keyword-based evidence extraction when AI is unavailable."""
    evidence = []
    lower = content.lower()

    # Try to find company name
    m = re.search(r"Title:\s*([^\n|—\-]+)", content)
    if m:
        evidence.append(f"Website title: {m.group(1).strip()[:80]}")

    # Employee counts
    for pat in [r"(\d[\d,]+)\s*(?:employees|staff|workers|team members)", r"employs\s+(?:over|more than|approximately)?\s*(\d[\d,]+)"]:
        m = re.search(pat, lower)
        if m:
            evidence.append(f"Workforce mention: approximately {m.group(1)} employees")
            break

    # Locations/sites
    for pat in [r"(\d+)\s*(?:locations|sites|facilities|warehouses|distribution cent(?:res|ers))", r"operations? (?:in|across) (\d+|\w+) (?:countries|states|regions)"]:
        m = re.search(pat, lower)
        if m:
            evidence.append(f"Operational footprint: {m.group(0)[:80]}")
            break

    # Certifications
    for cert in ["iso 45001", "iso 9001", "osha", "whs", "zero harm", "vision zero", "iso 14001"]:
        if cert in lower:
            evidence.append(f"Safety/quality certification mentioned: {cert.upper()}")

    # Industry signals
    for industry, keywords in [
        ("Logistics/warehousing", ["warehouse", "logistics", "distribution", "freight", "3pl"]),
        ("Manufacturing", ["manufacturing", "production", "assembly", "factory"]),
        ("Oil & Gas", ["oil", "gas", "refinery", "pipeline", "petroleum"]),
        ("Healthcare", ["hospital", "healthcare", "patient care", "clinical"]),
        ("Construction", ["construction", "civil", "infrastructure"]),
    ]:
        if any(k in lower for k in keywords):
            evidence.append(f"Industry signal: {industry} operations mentioned on website")
            break

    return evidence[:8] if evidence else [f"Limited content available from {url}"]


# ── Heuristic fallback (evidence-conditioned) ─────────────────────────────────

def heuristic_report(url: str, content: str, company_hint: str = "") -> Dict:
    """
    Fallback when AI is unavailable. Generates cautious, evidence-conditioned output.
    Never uses hardcoded logistics defaults — all recommendations flagged for validation.
    """
    lower = content.lower()
    company = company_hint or extract_company_name(url, content)

    # Score based on actual signals found
    score = 40  # baseline for any industrial prospect
    poc = 35

    vertical_signals = {
        "Logistics & Distribution":    ["logistics", "warehouse", "distribution", "freight", "fleet", "3pl", "supply chain"],
        "Manufacturing":               ["manufacturing", "plant", "factory", "production", "assembly"],
        "Energy / Utilities":          ["oil", "gas", "energy", "utility", "refinery", "pipeline"],
        "Healthcare Operations":       ["hospital", "healthcare", "clinic", "patient", "medical center"],
        "Construction & Infrastructure": ["construction", "civil", "infrastructure", "contractor"],
    }
    detected_vertical = "Industrial / Operations"
    for vertical, keywords in vertical_signals.items():
        if any(k in lower for k in keywords):
            detected_vertical = vertical
            score += 20
            break

    # Qualifying signals
    if any(k in lower for k in ["safety", "ehs", "hse", "osha", "iso 45001", "zero harm", "whs"]):
        score += 15
        poc += 15
    if any(k in lower for k in ["locations", "facilities", "sites", "global", "nationwide"]):
        score += 10
        poc += 10
    if any(k in lower for k in ["cctv", "camera", "video surveillance", "monitoring"]):
        score += 10
        poc += 20

    score = max(0, min(95, score))
    poc = max(0, min(90, poc))
    tier = ("Tier 1 — Strong ICP Match" if score >= 80 else
            "Tier 2 — Good Fit" if score >= 65 else
            "Tier 3 — Nurture" if score >= 45 else
            "Tier 4 — Deprioritize")

    # Extract evidence heuristically
    evidence = _extract_evidence_heuristic(url, content)
    limited = len(evidence) < 3 or len(content.split()) < 300

    # Build cautious, evidence-conditioned content
    if limited:
        why_now = (
            "Limited website evidence available — could not confirm specific operational triggers. "
            "Recommend a discovery call to determine: recent safety incidents, compliance pressure, "
            "site expansion activity, or technology refresh initiatives."
        )
        first_uc = "To be determined in discovery — insufficient public evidence to recommend a specific use case"
        safety_ucs = ["Validate in discovery: what safety risks are highest-priority for this organisation?"]
        ops_ucs = ["Validate in discovery: what operational KPIs are currently unmeasured or hard to monitor?"]
        stakeholders = ["Validate in discovery: who owns safety outcomes and operational performance KPIs?"]
        discovery_qs = [
            "What does your current safety monitoring process look like — who sees what, and how quickly?",
            "Where are the gaps in your visibility today across sites or shifts?",
            "Have you experienced any safety incidents or near-misses that were hard to detect early?",
            "What does success look like for you in improving operational visibility?",
            "Who else would need to be involved in evaluating a solution like this?",
        ]
        poc_rec = (
            "Limited evidence available to scope a specific POC. "
            "Recommend a discovery call to identify the highest-priority site and use case before proposing a pilot."
        )
        roi_narrative = (
            "ROI baseline data not available from website. "
            "Validate in discovery: incident frequency, audit frequency, current monitoring headcount, and site count."
        )
    else:
        # Evidence-conditioned content — only mention specifics we found
        safety_keywords_found = [k for k in ["safety", "ehs", "hse", "zero harm", "whs", "iso 45001", "osha"] if k in lower]
        has_safety = bool(safety_keywords_found)
        has_cameras = any(k in lower for k in ["cctv", "camera", "surveillance"])
        has_multisite = any(k in lower for k in ["locations", "facilities", "sites", "warehouses"])

        why_now = (
            f"{'Safety program signals (' + ', '.join(safety_keywords_found[:3]) + ') found on website — suggests safety outcomes are measurable and tracked. ' if has_safety else ''}"
            f"{'Multi-site operational footprint detected — standardising safety and operational visibility across sites is a common challenge. ' if has_multisite else ''}"
            "Validate current safety incident frequency, compliance deadlines, and any recent leadership changes or expansion during discovery."
        ).strip()

        first_uc = (
            f"To be confirmed in discovery based on {detected_vertical} operations — "
            f"{'likely a safety monitoring use case given safety program signals on website' if has_safety else 'no specific use case determinable from website content alone'}"
        )

        safety_ucs = (
            [f"Safety monitoring relevant to {detected_vertical} operations — specific use cases to confirm in discovery",
             "Validate: what high-risk interactions or zones are hardest to monitor manually today?"]
            if not has_safety else
            [f"Safety monitoring in {detected_vertical} context (safety program evidence found on website)",
             "Validate which specific risk types are highest priority — do not assume use case without discovery"]
        )

        ops_ucs = [
            f"Operational visibility for {detected_vertical} — specific use cases to validate in discovery",
            "Validate: which processes are currently measured manually or not at all?",
        ]

        stakeholders = [
            f"{'Safety/EHS leader (evidence of safety program found)' if has_safety else 'Safety or Operations leader — validate specific title in discovery'}",
            f"Operations leader responsible for {'multi-site' if has_multisite else 'site'} performance",
            "IT/Infrastructure owner if camera infrastructure needs to be assessed — validate in discovery",
        ]

        discovery_qs = [
            f"What does your current approach to safety monitoring look like across your {detected_vertical.lower()} operations?",
            "Where do you have the least visibility today — which sites, shifts, or processes are hardest to monitor?",
            "Have you had any safety incidents, near-misses, or audit findings in the past 12 months that were hard to detect early?",
            "What KPIs does leadership use to measure safety and operational performance — and which are hard to report on consistently?",
            "What existing camera or sensor infrastructure do you have in place today?",
        ]

        poc_rec = (
            f"Validate site selection and use case during discovery before scoping a POC. "
            f"Based on website signals: {detected_vertical} context, "
            f"{'safety program in place, ' if has_safety else ''}"
            f"{'camera infrastructure may exist. ' if has_cameras else 'camera infrastructure not confirmed — validate first. '}"
            "Aim for a 60–90 day pilot at one representative site."
        )

        roi_narrative = (
            f"ROI framework for {detected_vertical}: validate incident frequency, audit hours, and site count during discovery. "
            "Do not present financial ROI estimates until baselines are confirmed. "
            "Frame initial value as: improved visibility, faster response to incidents, and scalable monitoring without headcount increase."
        )

    return {
        "company_name": company,
        "website": url,
        "industry": detected_vertical,
        "description": summarize_description(content, company),
        "icp_score": score,
        "poc_fit_score": poc,
        "tier": tier,
        "company_evidence": evidence,
        "evidence_limited": limited,
        "why_now": why_now,
        "first_use_case": first_uc,
        "safety_use_cases": safety_ucs,
        "operations_use_cases": ops_ucs,
        "stakeholders": stakeholders,
        "discovery_questions": discovery_qs,
        "poc_recommendation": poc_rec,
        "roi_narrative": roi_narrative,
        "outreach_email": _draft_outreach_email(company, detected_vertical, evidence, limited),
        "linkedin_message": _draft_linkedin(company, detected_vertical, limited),
        "assumptions": [
            "All recommendations above are based on website signals only and must be validated in discovery.",
            "Camera/CCTV infrastructure not confirmed — validate before scoping a POC.",
            "Stakeholder titles are inferred — verify in LinkedIn Sales Navigator or CRM.",
            "ROI estimates not provided — baselines must be established in discovery.",
        ],
    }


def _draft_outreach_email(company: str, vertical: str, evidence: List[str], limited: bool) -> str:
    evidence_line = evidence[0] if evidence and not evidence[0].startswith("Limited") else ""
    if limited:
        return (
            f"Hi [Name],\n\n"
            f"I came across {company} and wanted to reach out — based on what I could see, "
            f"you're operating in a space where safety and operational visibility across sites tends to be a real challenge.\n\n"
            f"Rainscales helps teams use existing CCTV to detect safety risks and operational gaps in real time — "
            f"without adding headcount.\n\n"
            f"I'd love to understand what visibility looks like for your team today. "
            f"Would 20 minutes make sense this week?\n\nBest,\n[Your Name]"
        )
    return (
        f"Hi [Name],\n\n"
        f"I was researching {company} and noticed {evidence_line.lower() if evidence_line else f'you operate in {vertical.lower()}'} — "
        f"which is exactly the environment where our customers have struggled most with real-time safety and operational visibility.\n\n"
        f"Rainscales connects to existing CCTV to surface high-risk behaviours and operational gaps before they become incidents or reporting problems. "
        f"Teams like yours typically can't justify more monitoring headcount — so we give you scale through the cameras you already have.\n\n"
        f"Would it be worth a 20-minute call to see whether there's a fit?\n\nBest,\n[Your Name]"
    )


def _draft_linkedin(company: str, vertical: str, limited: bool) -> str:
    if limited:
        return (
            f"Hi [Name] — I came across {company} and thought Rainscales might be relevant "
            f"if your team is looking to improve safety visibility or operational monitoring across sites. "
            f"Open to a quick conversation?"
        )
    return (
        f"Hi [Name] — I was looking at {company}'s {vertical.lower()} operations and thought "
        f"there might be a relevant conversation to have about real-time safety and operational visibility. "
        f"Rainscales uses existing CCTV to do what manual monitoring can't scale to. Open to connecting?"
    )


def extract_company_name(url: str, content: str) -> str:
    m = re.search(r"Title:\s*([^\n|—\-]+)", content)
    if m and len(m.group(1).strip()) > 2:
        return m.group(1).strip()[:60]
    host = re.sub(r"https?://", "", url).split("/")[0].replace("www.", "")
    return host.split(".")[0].title()


def summarize_description(content: str, company: str) -> str:
    text = re.sub(r"\s+", " ", content).strip()
    return (text[:280] + "...") if len(text) > 280 else text


# ── AI analysis ──────────────────────────────────────────────────────────────

def ai_report(url: str, content: str, company_hint: str = "") -> Dict:
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key or Anthropic is None:
        return heuristic_report(url, content, company_hint)

    client = Anthropic(api_key=key)

    # ── Step 1: Extract company evidence ──────────────────────────────────────
    evidence, evidence_limited = extract_company_evidence(url, content, client)

    evidence_block = "\n".join(f"- {e}" for e in evidence)
    limited_instruction = (
        "IMPORTANT: Website evidence is LIMITED. Set evidence_limited to true. "
        "Make all use cases, stakeholders, and recommendations cautious and exploratory. "
        "Prefix recommendations with 'Validate in discovery:' rather than stating them as facts."
        if evidence_limited else
        "Evidence is sufficient for specific recommendations."
    )

    # ── Step 2: Generate evidence-grounded recommendations ───────────────────
    prompt = f"""You are the Rainscales GTM Intelligence engine. Your job is to qualify a prospect for Rainscales — an AI-powered detection platform that uses existing CCTV and sensors to improve safety and operational visibility in industrial environments.

{ICP_PROFILE}

COMPANY EVIDENCE EXTRACTED FROM WEBSITE:
{evidence_block}

{limited_instruction}

STRICT RULES — you MUST follow all of these:
1. NO EVIDENCE, NO RECOMMENDATION. Every use case, stakeholder title, discovery question, POC recommendation, and ROI claim must be grounded in at least one evidence point (website OR external intelligence).
2. External intelligence (Reddit, news, OSHA, job postings, reviews) is LOWER CONFIDENCE than the company website. Use it to generate hypotheses and targeted discovery questions — flag it: "Based on job postings...", "News reports suggest...", "Glassdoor reviews indicate..."
3. OSHA violations or safety incidents from external sources are HIGH VALUE buying signals — always surface in why_now and outreach_email.
4. Job postings reveal pain: open EHS/safety roles = unfilled headcount gap; job descriptions list exact tools and problems.
5. DO NOT use these generic defaults unless the evidence directly supports them:
   - "Forklift/Pedestrian Interaction" — only if forklifts are mentioned in the evidence
   - "PPE compliance monitoring" — only if PPE or safety gear is mentioned in the evidence
   - "Loading dock throughput" — only if loading docks or throughput are mentioned
   - "VP/Director of EHS" — only if an EHS team or EHS role is explicitly mentioned in the evidence
   - Generic ROI numbers (e.g. "$250K per incident") — only if incident costs are mentioned
3. If you cannot make a specific recommendation from the evidence, say "Validate in discovery: [what to ask]" instead.
4. Use the ICP Profile above to score the prospect and frame outreach language.
5. Keep all lists to 3–5 items maximum.
6. All copy (email, LinkedIn) must feel tailored to this specific company's evidence — not a generic logistics template.

Return ONLY valid JSON with these exact keys:
company_name, website, industry, description, icp_score (0-100), poc_fit_score (0-100), tier,
company_evidence (array — copy from above), evidence_limited (bool),
why_now, first_use_case, safety_use_cases (array), operations_use_cases (array),
stakeholders (array), discovery_questions (array), poc_recommendation,
roi_narrative, outreach_email, linkedin_message, assumptions (array)

URL: {url}
Company hint: {company_hint or "not provided"}
Full website content:
{content[:22000]}"""

    try:
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=5000,
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        text = re.sub(r"^```json|```$", "", text, flags=re.MULTILINE).strip()
        data = json.loads(text)

        # Ensure evidence fields are always present
        data.setdefault("company_evidence", evidence)
        data.setdefault("evidence_limited", evidence_limited)

        # Merge with heuristic fallback for any missing fields
        fallback = heuristic_report(url, content, company_hint)
        for k in fallback:
            if k not in data or data[k] is None:
                data[k] = fallback[k]

        return data

    except Exception as e:
        data = heuristic_report(url, content, company_hint)
        data["company_evidence"] = evidence
        data["evidence_limited"] = evidence_limited
        data["assumptions"].append(f"AI generation failed; evidence-conditioned heuristic used: {str(e)[:120]}")
        return data


# ── HTML report renderer ─────────────────────────────────────────────────────


def render_report(data: Dict) -> str:
    slug = slugify(data.get("company_name") or data.get("website"))
    filename = f"{slug}-qualification-report.html"
    path = REPORTS / filename

    def esc(v):
        return html.escape(str(v or ""))

    def _coerce_str(v) -> str:
        if isinstance(v, dict):
            for k in ("description", "body", "rationale", "name", "title", "text"):
                if v.get(k):
                    return str(v[k])
            return " ".join(str(x) for x in v.values() if x)
        if isinstance(v, list):
            return " ".join(_coerce_str(x) for x in v)
        return str(v or "")

    def render_use_case_card(item) -> str:
        if isinstance(item, dict):
            name = esc(item.get("name", ""))
            desc = esc(item.get("description", ""))
            evidence = esc(item.get("evidence_basis", ""))
            parts = []
            if name:
                parts.append(f'<strong>{name}</strong>')
            if desc:
                parts.append(f'<p>{desc}</p>')
            if evidence:
                parts.append(f'<p class="evidence-tag">Evidence: {evidence}</p>')
            return f'<div class="card">{"".join(parts)}</div>'
        return f'<div class="card"><p>{esc(_coerce_str(item))}</p></div>'

    def render_stakeholder(item) -> str:
        if isinstance(item, dict):
            title = esc(item.get("title", ""))
            rationale = esc(item.get("rationale", ""))
            icp_match = esc(item.get("icp_match", ""))
            parts = []
            if title:
                parts.append(f'<strong>{title}</strong>')
            if icp_match:
                parts.append(f' <span class="badge">{icp_match}</span>')
            if rationale:
                parts.append(f'<br><span class="rationale">{rationale}</span>')
            return f'<li>{"".join(parts)}</li>'
        return f'<li>{esc(_coerce_str(item))}</li>'

    def render_first_use_case(item) -> str:
        if isinstance(item, dict):
            name = esc(item.get("name", ""))
            desc = esc(item.get("description", ""))
            evidence = esc(item.get("evidence_basis", ""))
            value_prop = esc(item.get("value_proposition", ""))
            parts = []
            if name:
                parts.append(f'<h3>{name}</h3>')
            if desc:
                parts.append(f'<p>{desc}</p>')
            if evidence:
                parts.append(f'<p class="evidence-tag">Evidence: {evidence}</p>')
            if value_prop:
                parts.append(f'<p class="value-prop">{value_prop}</p>')
            return "".join(parts)
        return f'<p>{esc(_coerce_str(item))}</p>'

    def render_why_now(item) -> str:
        if isinstance(item, list):
            return "<ul>" + "".join(f"<li>{esc(_coerce_str(x))}</li>" for x in item) + "</ul>"
        if isinstance(item, dict):
            parts = []
            for v in item.values():
                if v:
                    parts.append(f"<li>{esc(_coerce_str(v))}</li>")
            return "<ul>" + "".join(parts) + "</ul>"
        text = str(item or "")
        sentences = [s.strip() for s in re.split(r'\.\s+', text) if len(s.strip()) > 20]
        if len(sentences) >= 3:
            return "<ul>" + "".join(f"<li>{esc(s)}.</li>" for s in sentences) + "</ul>"
        return f"<p>{esc(text)}</p>"

    def render_poc(item) -> str:
        if isinstance(item, dict):
            scope = esc(item.get("suggested_scope", ""))
            duration = esc(item.get("duration", ""))
            rationale = esc(item.get("rationale", ""))
            metrics = item.get("success_metrics", [])
            parts = []
            if scope:
                parts.append(f'<p><strong>Scope:</strong> {scope}</p>')
            if duration:
                parts.append(f'<p><strong>Duration:</strong> {duration}</p>')
            if rationale:
                parts.append(f'<p>{rationale}</p>')
            if metrics:
                parts.append('<p><strong>Success Metrics:</strong></p><ul>')
                for m in (metrics if isinstance(metrics, list) else [metrics]):
                    parts.append(f'<li>{esc(_coerce_str(m))}</li>')
                parts.append('</ul>')
            return "".join(parts)
        text = str(item or "")
        sentences = [s.strip() for s in re.split(r'\.\s+', text) if len(s.strip()) > 20]
        if len(sentences) >= 3:
            return "<ul>" + "".join(f"<li>{esc(s)}.</li>" for s in sentences) + "</ul>"
        return f"<p>{esc(text)}</p>"

    def render_roi(item) -> str:
        text = _coerce_str(item)
        sentences = [s.strip() for s in re.split(r'\.\s+', text) if len(s.strip()) > 20]
        if len(sentences) >= 3:
            return "<ul>" + "".join(f"<li>{esc(s)}.</li>" for s in sentences) + "</ul>"
        return f"<p>{esc(text)}</p>"

    def render_email(item) -> str:
        if isinstance(item, dict):
            subject = item.get("subject", "")
            body = item.get("body", "")
            body = body.replace("\\n", "\n")
            out = ""
            if subject:
                out += f'<p class="email-subject"><strong>Subject:</strong> {esc(subject)}</p>'
            if body:
                out += f'<pre>{esc(body)}</pre>'
            return out or f'<pre>{esc(_coerce_str(item))}</pre>'
        text = str(item or "").replace("\\n", "\n")
        return f'<pre>{esc(text)}</pre>'

    def list_items(items):
        return "".join(f"<li>{esc(_coerce_str(x))}</li>" for x in (items or []))

    score = int(data.get("icp_score", 0))
    poc   = int(data.get("poc_fit_score", 0))
    tier_class = "tier1" if score >= 80 else "tier2" if score >= 65 else "tier3" if score >= 45 else "tier4"
    evidence_limited = data.get("evidence_limited", False)

    evidence_items = data.get("company_evidence") or []
    if evidence_limited:
        ev_items_html = "".join(f"<li>{esc(e)}</li>" for e in evidence_items)
        evidence_html = (
            '<div class="evidence-banner">'
            '<div class="evidence-header">Warning: Limited Website Evidence</div>'
            f'<p class="evidence-note">Only {len(evidence_items)} evidence point(s) found. '
            'All recommendations below are cautious and exploratory - validate everything in discovery.</p>'
            f'<ul>{ev_items_html}</ul>'
            '</div>'
        )
    else:
        ev_items_html = "".join(f"<li>{esc(e)}</li>" for e in evidence_items)
        evidence_html = (
            '<div class="evidence-section">'
            '<h2>Company Evidence Used</h2>'
            '<p class="evidence-note">All recommendations in this report are grounded in the following facts '
            "found on the company's website. No recommendation is made without supporting evidence.</p>"
            f'<ul class="evidence-list">{ev_items_html}</ul>'
            '</div>'
        )

    safety_cards = "".join(render_use_case_card(x) for x in (data.get("safety_use_cases") or []))
    ops_cards = "".join(render_use_case_card(x) for x in (data.get("operations_use_cases") or []))
    stakeholder_items = "".join(render_stakeholder(x) for x in (data.get("stakeholders") or []))

    html_doc = (
        "<!doctype html>\n"
        "<html><head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{esc(data["company_name"])} - Rainscales Qualification Report</title>'
        '<link rel="stylesheet" href="/static/styles.css">'
        "<style>\n"
        '.evidence-section{background:rgba(97,201,217,.06);border:1px solid rgba(97,201,217,.25);border-radius:14px;padding:20px 22px;margin:18px 0}\n'
        '.evidence-section h2{color:#61C9D9;font-size:16px;margin:0 0 8px}\n'
        '.evidence-note{color:#aab7d0;font-size:13px;margin:0 0 12px}\n'
        '.evidence-list li{color:#e2e8f0;font-size:14px;margin:5px 0;padding-left:4px}\n'
        '.evidence-banner{background:rgba(245,158,11,.1);border:1px solid rgba(245,158,11,.35);border-radius:14px;padding:18px 20px;margin:18px 0}\n'
        '.evidence-header{color:#f59e0b;font-weight:700;font-size:15px;margin-bottom:8px}\n'
        '.evidence-banner .evidence-note{color:#fcd34d}\n'
        '.evidence-banner li{color:#fde68a;font-size:13px;margin:4px 0}\n'
        '.evidence-tag{color:#61C9D9;font-size:12px;margin:4px 0 0;font-style:italic}\n'
        '.value-prop{color:#a78bfa;font-size:13px;margin:8px 0 0;border-left:3px solid #a78bfa;padding-left:10px}\n'
        '.badge{background:rgba(97,201,217,.15);color:#61C9D9;font-size:11px;padding:2px 7px;border-radius:99px;margin-left:6px;vertical-align:middle}\n'
        '.rationale{color:#aab7d0;font-size:13px}\n'
        '.email-subject{margin-bottom:8px;color:#e2e8f0}\n'
        "</style>\n"
        "</head>\n"
        "<body><main class='wrap'>\n"
        "<header class='hero'>\n"
        "<div>\n"
        "  <div class='eyebrow'>Rainscales GTM Intelligence</div>\n"
        f"  <h1>{esc(data['company_name'])}</h1>\n"
        f"  <a href='{esc(data['website'])}'>{esc(data['website'])}</a>\n"
        f"  <p>{esc(data['description'])}</p>\n"
        "</div>\n"
        f"<div class='score {tier_class}'><span>{score}</span><small>ICP Score</small><em>{esc(data['tier'])}</em></div>\n"
        f"<div class='score poc'><span>{poc}</span><small>POC Fit</small>"
        f"<em>{'Limited evidence' if evidence_limited else 'Validate assumptions'}</em></div>\n"
        "</header>\n\n"
        + evidence_html + "\n\n"
        + f"<section><h2>Why Now</h2>{render_why_now(data['why_now'])}</section>\n"
        + f"<section><h2>Recommended First Use Case</h2><div class='highlight'>{render_first_use_case(data['first_use_case'])}</div></section>\n"
        + f"<section class='grid'><div><h2>Safety Use Cases</h2>{safety_cards}</div>"
        + f"<div><h2>Operational Use Cases</h2>{ops_cards}</div></section>\n"
        + f"<section class='grid'>"
        + f"<div><h2>Stakeholders</h2><ul>{stakeholder_items}</ul></div>"
        + f"<div><h2>Discovery Questions</h2><ul>{list_items(data.get('discovery_questions'))}</ul></div>"
        + f"</section>\n"
        + f"<section><h2>POC Recommendation</h2>{render_poc(data['poc_recommendation'])}</section>\n"
        + f"<section><h2>ROI Narrative</h2>{render_roi(data['roi_narrative'])}</section>\n"
        + f"<section class='grid'>"
        + f"<div><h2>Email</h2>{render_email(data['outreach_email'])}</div>"
        + f"<div><h2>LinkedIn</h2><pre>{esc(_coerce_str(data.get('linkedin_message', '')))}</pre></div>"
        + f"</section>\n"
        + f"<section><h2>Assumptions to Validate</h2><ul>{list_items(data.get('assumptions'))}</ul></section>\n"
        + f"<footer>Generated {date.today().isoformat()} - Rainscales Prospect Qualification Portal</footer>\n"
        + "</main></body></html>"
    )

    path.write_text(html_doc, encoding="utf-8")
    return filename


# ── Public API ────────────────────────────────────────────────────────────────

def analyze(url: str, company_hint: str = "") -> ProspectReport:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    content = fetch_site(url)
    company_name = company_hint or extract_company_name(url, content)
    intelligence = gather_intelligence(url, company_name)
    if intelligence:
        sep = "\n" + "=" * 60 + "\n"
        header = "EXTERNAL INTELLIGENCE (Reddit, news, jobs, reviews, OSHA)\n"
        subhead = "Lower confidence than direct site content.\n"
        content = content + sep + header + subhead + "=" * 60 + "\n" + intelligence
    data = ai_report(url, content, company_hint)
    data["website"] = url
    report_file = render_report(data)
    data["report_file"] = report_file
    return ProspectReport(**data)


def batch_analyze(csv_path: Path) -> List[ProspectReport]:
    results = []

    with csv_path.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            website = (
                row.get("Website") or row.get("website") or
                row.get("URL") or row.get("url") or
                row.get("Company Website") or row.get("Website URL") or ""
            ).strip()
            company = (
                row.get("Company Name") or row.get("Company") or
                row.get("company") or row.get("Name") or ""
            ).strip()

            if not website:
                continue

            try:
                results.append(analyze(website, company))
                time.sleep(0.5)
            except Exception as e:
                results.append({
                    "company_name": company or website,
                    "website": website,
                    "industry": row.get("Industry", ""),
                    "icp_score": 0,
                    "poc_fit_score": 0,
                    "tier": "Error",
                    "first_use_case": f"Skipped: {e}",
                    "report_file": "",
                })
                continue

    # Write batch-summary.csv
    summary = REPORTS / "batch-summary.csv"
    with summary.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "company_name", "website", "industry", "icp_score", "poc_fit_score",
            "tier", "first_use_case", "report_file",
        ])
        writer.writeheader()
        for r in results:
            d = asdict(r) if hasattr(r, "__dataclass_fields__") else r
            writer.writerow({k: d.get(k, "") for k in writer.fieldnames})

    return results

