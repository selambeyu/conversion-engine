"""
enrichment/signal_brief.py
─────────────────────────────────────────────────────
Researches a company from public data and returns
a hiring_signal_brief dict the email agent uses
to write a personalised, grounded email.

Steps:
  1. Look up company in Crunchbase dataset
  2. Check layoffs.fyi for recent layoffs
  3. Score AI maturity 0-3
  4. Classify into 1 of 4 ICP segments
  5. Return everything as one dict
─────────────────────────────────────────────────────
"""

import os
import csv
import json
import requests
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

DATA_DIR       = Path(__file__).parent.parent / "data"
CRUNCHBASE_CSV = DATA_DIR / "crunchbase_sample.csv"
LAYOFFS_CSV    = DATA_DIR / "layoffs.csv"


# ─────────────────────────────────────────────────────────
# STEP 0 — Download data files (run once)
# ─────────────────────────────────────────────────────────

def download_data_files():
    DATA_DIR.mkdir(exist_ok=True)

    if not CRUNCHBASE_CSV.exists():
        print("Downloading Crunchbase sample...")
        try:
            url  = ("https://raw.githubusercontent.com/luminati-io/"
                    "Crunchbase-dataset-samples/main/"
                    "crunchbase-dataset-samples.csv")
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            CRUNCHBASE_CSV.write_text(resp.text, encoding="utf-8")
            print(f"  Saved → {CRUNCHBASE_CSV}")
        except Exception as e:
            print(f"  Download failed: {e} — creating sample data")
            _create_sample_crunchbase()
    else:
        print(f"  Crunchbase OK → {CRUNCHBASE_CSV}")

    if not LAYOFFS_CSV.exists():
        print("Downloading layoffs data...")
        try:
            url  = ("https://raw.githubusercontent.com/datasets/"
                    "layoffs/main/data/layoffs.csv")
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            LAYOFFS_CSV.write_text(resp.text, encoding="utf-8")
            print(f"  Saved → {LAYOFFS_CSV}")
        except Exception as e:
            print(f"  Download failed: {e} — creating sample data")
            _create_sample_layoffs()
    else:
        print(f"  Layoffs OK → {LAYOFFS_CSV}")


def _create_sample_crunchbase():
    rows = [
        "name,description,employee_count,total_funding_usd,last_funding_type,last_funding_date,industry,country,city,homepage_url",
        "Acme AI,AI-powered analytics platform,45,12000000,Series A,2026-02-15,Artificial Intelligence,USA,San Francisco,acmeai.com",
        "DataFlow Inc,Real-time data pipeline software,120,28000000,Series B,2025-11-20,Data Analytics,USA,New York,dataflow.io",
        "CloudScale,Cloud infrastructure management,320,85000000,Series C,2025-08-10,Cloud Computing,USA,Seattle,cloudscale.com",
        "MicroTech,Microservices development platform,67,18500000,Series A,2026-01-08,Developer Tools,USA,Austin,microtech.dev",
        "FinEdge,Fintech compliance automation,89,22000000,Series B,2025-12-01,Financial Technology,USA,Chicago,finedge.io",
        "RoboOps,Industrial automation software,156,45000000,Series B,2026-03-12,Robotics,USA,Detroit,roboops.com",
        "HealthAI,Healthcare AI diagnostics,78,31000000,Series B,2025-10-15,Health Technology,USA,Boston,healthai.com",
        "SecureNet,Cybersecurity platform,234,67000000,Series C,2025-09-20,Cybersecurity,USA,Washington DC,securenet.io",
        "LogiChain,Supply chain optimization,112,29000000,Series B,2026-02-28,Logistics Technology,USA,Chicago,logichain.com",
        "EduPlatform,Online learning management,445,112000000,Series D,2025-07-15,Education Technology,USA,New York,eduplatform.com",
    ]
    CRUNCHBASE_CSV.write_text("\n".join(rows), encoding="utf-8")
    print(f"  Sample Crunchbase created → {CRUNCHBASE_CSV}")


def _create_sample_layoffs():
    rows = [
        "Company,Industry,Laid_Off_Count,Date,Percentage,Country,Stage",
        "CloudScale,Cloud Computing,45,2025-12-15,14%,USA,Series C",
        "FinEdge,Financial Technology,12,2026-01-20,13%,USA,Series B",
        "EduPlatform,Education Technology,89,2025-11-10,20%,USA,Series D",
        "SecureNet,Cybersecurity,23,2026-02-01,10%,USA,Series C",
    ]
    LAYOFFS_CSV.write_text("\n".join(rows), encoding="utf-8")
    print(f"  Sample layoffs created → {LAYOFFS_CSV}")


# ─────────────────────────────────────────────────────────
# STEP 1 — Crunchbase lookup
# ─────────────────────────────────────────────────────────

def lookup_crunchbase(company_name: str) -> dict:
    if not CRUNCHBASE_CSV.exists():
        return {}
    name_lower = company_name.lower().strip()
    try:
        with open(CRUNCHBASE_CSV, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if name_lower in row.get("name", "").lower():
                    return {
                        "name":              row.get("name", ""),
                        "description":       row.get("description", ""),
                        "employee_count":    int(row.get("employee_count", 0) or 0),
                        "total_funding_usd": float(row.get("total_funding_usd", 0) or 0),
                        "last_funding_type": row.get("last_funding_type", ""),
                        "last_funding_date": row.get("last_funding_date", ""),
                        "industry":          row.get("industry", ""),
                        "country":           row.get("country", ""),
                        "city":              row.get("city", ""),
                        "homepage_url":      row.get("homepage_url", ""),
                    }
    except Exception as e:
        print(f"  Crunchbase read error: {e}")
    return {}


# ─────────────────────────────────────────────────────────
# STEP 2 — Layoffs check
# ─────────────────────────────────────────────────────────

def check_layoffs(company_name: str, days: int = 120) -> dict:
    if not LAYOFFS_CSV.exists():
        return {}
    name_lower = company_name.lower().strip()
    cutoff     = datetime.now() - timedelta(days=days)
    try:
        with open(LAYOFFS_CSV, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if name_lower not in row.get("Company", "").lower():
                    continue
                try:
                    date = datetime.strptime(row["Date"][:10], "%Y-%m-%d")
                    if date >= cutoff:
                        return {
                            "had_layoffs":    True,
                            "layoff_count":   int(row.get("Laid_Off_Count", 0) or 0),
                            "most_recent":    row.get("Date", ""),
                            "percentage_cut": row.get("Percentage", ""),
                            "signal":         "cost_pressure",
                        }
                except Exception:
                    continue
    except Exception as e:
        print(f"  Layoffs read error: {e}")
    return {}


# ─────────────────────────────────────────────────────────
# STEP 3 — AI maturity score
# ─────────────────────────────────────────────────────────

def score_ai_maturity(crunchbase: dict, open_roles: int = 0) -> dict:
    score    = 0
    evidence = []
    low_conf = []

    desc     = crunchbase.get("description", "").lower()
    industry = crunchbase.get("industry", "").lower()

    # Industry signal (high weight)
    ai_industries = ["artificial intelligence", "machine learning",
                     "data analytics", "data science", "mlops"]
    if any(ai in industry for ai in ai_industries):
        score += 2
        evidence.append(f"AI industry: {crunchbase.get('industry')}")

    # Description keywords (medium weight)
    ai_kw = ["ai", "ml", "machine learning", "llm", "neural",
              "model", "inference", "generative", "deep learning"]
    hits  = [kw for kw in ai_kw if kw in desc]
    if len(hits) >= 3:
        score += 1
        evidence.append(f"AI keywords: {hits[:3]}")
    elif hits:
        low_conf.append(f"Weak AI signal: {hits[:2]}")

    # Open roles (high weight)
    if open_roles >= 5:
        score += 1
        evidence.append(f"{open_roles} open engineering roles")
    elif open_roles >= 1:
        low_conf.append(f"Only {open_roles} open role(s)")

    score = min(score, 3)

    if score >= 2 and not low_conf:
        confidence = "high"
    elif score >= 1 or evidence:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "score":      score,
        "confidence": confidence,
        "evidence":   evidence,
        "low_conf":   low_conf,
    }


# ─────────────────────────────────────────────────────────
# STEP 4 — ICP segment classifier
# ─────────────────────────────────────────────────────────

def classify_segment(crunchbase: dict, layoffs: dict,
                     ai_maturity: dict) -> dict:
    employees   = crunchbase.get("employee_count", 0)
    funding     = crunchbase.get("total_funding_usd", 0)
    fund_type   = crunchbase.get("last_funding_type", "").lower()
    fund_date   = crunchbase.get("last_funding_date", "")
    ai_score    = ai_maturity.get("score", 0)
    had_layoffs = layoffs.get("had_layoffs", False)

    scores = {
        "recently_funded_startup":           0,
        "mid_market_restructuring":          0,
        "engineering_leadership_transition": 0,
        "specialized_capability_gap":        0,
    }

    # Segment 1 — fresh startup
    if fund_type in ["series a", "series b", "seed"]:
        scores["recently_funded_startup"] += 2
    if 5_000_000 <= funding <= 30_000_000:
        scores["recently_funded_startup"] += 2
    if 15 <= employees <= 80:
        scores["recently_funded_startup"] += 1
    if not had_layoffs:
        scores["recently_funded_startup"] += 1
    try:
        fdate = datetime.strptime(fund_date[:10], "%Y-%m-%d")
        if (datetime.now() - fdate).days <= 180:
            scores["recently_funded_startup"] += 3
    except Exception:
        pass

    # Segment 2 — cost restructuring
    if had_layoffs:
        scores["mid_market_restructuring"] += 4
    if 200 <= employees <= 2000:
        scores["mid_market_restructuring"] += 2
    if funding > 30_000_000:
        scores["mid_market_restructuring"] += 1

    # Segment 4 — capability gap
    if ai_score >= 2:
        scores["specialized_capability_gap"] += 3
    if ai_score == 3:
        scores["specialized_capability_gap"] += 2
    if employees >= 50:
        scores["specialized_capability_gap"] += 1

    best      = max(scores, key=scores.get)
    raw_score = scores[best]

    if raw_score >= 5:
        confidence = "high"
    elif raw_score >= 3:
        confidence = "medium"
    else:
        confidence = "low"
        best       = "unknown"

    return {
        "segment":      best,
        "confidence":   confidence,
        "all_scores":   scores,
        "send_generic": confidence == "low",
    }


# ─────────────────────────────────────────────────────────
# STEP 5 — Build the full brief
# ─────────────────────────────────────────────────────────

def build_signal_brief(
    company_name: str,
    open_roles: int = 0,
    careers_url: str = "",
    scrape_jobs: bool = True,
) -> dict:
    """
    Main function. Call this for every prospect.
    Returns the hiring_signal_brief dict.
    """
    print(f"\nBuilding signal brief: {company_name}")

    crunchbase  = lookup_crunchbase(company_name)
    layoffs     = check_layoffs(company_name)

    # Job-post velocity signal via Playwright (public pages only)
    job_signal: dict = {}
    if scrape_jobs:
        try:
            from enrichment.job_post_scraper import scrape_job_posts
            job_signal = scrape_job_posts(company_name, careers_url=careers_url)
            # Use scraped role count to supplement open_roles if caller passed 0
            if open_roles == 0 and job_signal.get("engineering_roles", 0) > 0:
                open_roles = job_signal["engineering_roles"]
        except Exception as e:
            print(f"  Job scrape skipped: {e}")

    ai_maturity = score_ai_maturity(crunchbase, open_roles)
    segment     = classify_segment(crunchbase, layoffs, ai_maturity)

    pitch_map = {
        "recently_funded_startup":           "scale_engineering_fast",
        "mid_market_restructuring":          "reduce_cost_keep_output",
        "engineering_leadership_transition": "reassess_vendor_mix",
        "specialized_capability_gap":        "fill_ai_skill_gap",
        "unknown":                           "exploratory_discovery",
    }

    seg         = segment["segment"]
    pitch_angle = pitch_map.get(seg, "exploratory_discovery")

    # Plain-English summary for the email agent
    parts = []
    emp   = crunchbase.get("employee_count", 0)
    fund  = crunchbase.get("total_funding_usd", 0)
    ftype = crunchbase.get("last_funding_type", "")
    fdate = crunchbase.get("last_funding_date", "")
    city  = crunchbase.get("city", "")
    ind   = crunchbase.get("industry", "")

    if emp and ind:
        parts.append(
            f"{company_name} is a {emp}-person {ind} company"
            + (f" in {city}." if city else ".")
        )
    if fund and ftype:
        parts.append(
            f"They raised ${fund/1e6:.0f}M ({ftype})"
            + (f" in {fdate[:7]}." if fdate else ".")
        )
    if layoffs.get("had_layoffs"):
        parts.append(
            f"They had recent layoffs "
            f"({layoffs.get('percentage_cut','')} of headcount)."
        )
    ai_s = ai_maturity["score"]
    ai_c = ai_maturity["confidence"]
    if ai_s >= 2:
        parts.append(
            f"AI maturity {ai_s}/3 ({ai_c} confidence). "
            f"Evidence: {'; '.join(ai_maturity['evidence'][:2])}."
        )
    elif ai_s == 1:
        parts.append("Early AI interest (score 1/3), no dedicated function yet.")
    else:
        parts.append("No clear public AI signal found.")

    parts.append(
        f"ICP segment: {seg} ({segment['confidence']} confidence). "
        f"Pitch: {pitch_angle.replace('_',' ')}."
    )

    if segment["send_generic"] or ai_c == "low":
        parts.append(
            "IMPORTANT: Low confidence — use exploratory language, "
            "ask rather than assert."
        )

    # Job-post velocity sentence
    if job_signal:
        vel = job_signal.get("velocity_signal", "low")
        tot = job_signal.get("total_listings", 0)
        ai_r = job_signal.get("ai_ml_roles", 0)
        src  = job_signal.get("sources_scraped", [])
        job_conf = job_signal.get("confidence", "low")
        parts.append(
            f"Job-post velocity: {vel} ({tot} public listings via {src}, "
            f"{ai_r} AI/ML roles, confidence={job_conf})."
        )

    summary = " ".join(parts)

    brief = {
        "company_name":       company_name,
        "enriched_at":        datetime.utcnow().isoformat(),
        "firmographics":      crunchbase,
        "layoff_signal":      layoffs,
        "open_roles_count":   open_roles,
        "ai_maturity_score":  ai_maturity["score"],
        "ai_maturity_conf":   ai_maturity["confidence"],
        "ai_evidence":        ai_maturity["evidence"],
        "segment":            seg,
        "segment_confidence": segment["confidence"],
        "send_generic_email": segment["send_generic"],
        "all_segment_scores": segment["all_scores"],
        "pitch_angle":        pitch_angle,
        "summary":            summary,
        # Job-post velocity signal (Playwright public scrape)
        "hiring_signal_brief": {
            **job_signal,
            "confidence": job_signal.get("confidence", "low"),
            "evidence":   job_signal.get("evidence", "No job scrape data available."),
        } if job_signal else {
            "source": "none",
            "confidence": "low",
            "evidence": "Job scraping skipped or returned no data.",
            "total_listings": 0,
            "engineering_roles": 0,
            "ai_ml_roles": 0,
            "velocity_signal": "low",
        },
    }

    print(f"  Segment:     {seg} ({segment['confidence']})")
    print(f"  AI maturity: {ai_maturity['score']}/3 ({ai_maturity['confidence']})")
    print(f"  Pitch:       {pitch_angle}")
    if job_signal:
        print(f"  Job signal:  {job_signal.get('total_listings',0)} listings "
              f"| velocity={job_signal.get('velocity_signal','low')} "
              f"| confidence={job_signal.get('confidence','low')}")
    return brief