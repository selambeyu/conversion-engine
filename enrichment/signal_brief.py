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
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

DATA_DIR       = Path(__file__).parent.parent / "data"
CRUNCHBASE_CSV = DATA_DIR / "crunchbase-companies-information.csv"
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
# STEP 1 — Crunchbase lookup (real ODM dataset)
# ─────────────────────────────────────────────────────────

def _parse_employee_count(raw: str) -> int:
    """Convert '51-100' or '1-10' range string to midpoint int."""
    if not raw:
        return 0
    raw = str(raw).strip()
    if "-" in raw:
        try:
            lo, hi = raw.split("-", 1)
            return (int(lo.replace(",","")) + int(hi.replace(",",""))) // 2
        except Exception:
            pass
    try:
        return int(raw.replace(",",""))
    except Exception:
        return 0


def _parse_funding_rounds(raw: str) -> tuple:
    """
    Parse funding_rounds_list JSON column.
    Returns (last_funding_type, last_funding_date, total_funding_usd).
    """
    if not raw or raw in ("[]", "null", ""):
        return "", "", 0.0
    try:
        rounds = json.loads(raw)
        if not rounds:
            return "", "", 0.0
        # Sort by announced_on descending to get most recent
        rounds_sorted = sorted(
            [r for r in rounds if r.get("announced_on")],
            key=lambda r: r.get("announced_on", ""),
            reverse=True
        )
        last = rounds_sorted[0] if rounds_sorted else rounds[0]
        total = sum(
            float(r.get("money_raised", {}).get("value_usd", 0) or 0)
            for r in rounds
        )
        return (
            last.get("investment_type", ""),
            last.get("announced_on", ""),
            total,
        )
    except Exception:
        return "", "", 0.0


def _parse_industries(raw: str) -> str:
    """Parse industries JSON column → comma-separated string."""
    if not raw or raw in ("null", "[]", ""):
        return ""
    try:
        items = json.loads(raw)
        return ", ".join(i.get("value", "") for i in items if i.get("value"))
    except Exception:
        return raw


def _parse_leadership_hire(raw: str) -> bool:
    """Return True if there is any leadership hire in the last 90 days."""
    if not raw or raw in ("null", "[]", ""):
        return False
    try:
        hires = json.loads(raw)
        if not hires:
            return False
        cutoff = datetime.now() - timedelta(days=90)
        for h in hires:
            date_str = h.get("started_on", "") or h.get("announced_on", "")
            if date_str:
                try:
                    if datetime.strptime(date_str[:10], "%Y-%m-%d") >= cutoff:
                        return True
                except Exception:
                    pass
        return bool(hires)  # has hires but no dates — assume recent
    except Exception:
        return False


def _parse_builtwith_tech(raw: str) -> list:
    """Return list of technology names from builtwith_tech column."""
    if not raw or raw in ("null", "[]", ""):
        return []
    try:
        techs = json.loads(raw)
        return [t.get("name", "") for t in techs if t.get("name")]
    except Exception:
        return []


def _parse_layoff_field(raw: str) -> bool:
    """Return True if the inline layoff field has any data."""
    if not raw or raw in ("null", "[]", ""):
        return False
    try:
        items = json.loads(raw)
        return bool(items)
    except Exception:
        return False


def lookup_crunchbase(company_name: str) -> dict:
    if not CRUNCHBASE_CSV.exists():
        return {}
    name_lower = company_name.lower().strip()
    try:
        with open(CRUNCHBASE_CSV, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if name_lower in row.get("name", "").lower():
                    fund_type, fund_date, total_funding = _parse_funding_rounds(
                        row.get("funding_rounds_list", "")
                    )
                    emp_count = _parse_employee_count(row.get("num_employees", ""))
                    industry  = _parse_industries(row.get("industries", ""))
                    tech_list = _parse_builtwith_tech(row.get("builtwith_tech", ""))
                    has_leadership_hire = _parse_leadership_hire(row.get("leadership_hire", ""))
                    has_layoff_inline   = _parse_layoff_field(row.get("layoff", ""))

                    # Location — extract first city name from JSON array or plain string
                    raw_loc  = row.get("location", "") or row.get("region", "")
                    try:
                        loc_list = json.loads(raw_loc)
                        location = loc_list[0].get("name", "") if loc_list else ""
                    except Exception:
                        location = raw_loc
                    country = row.get("country_code", "")

                    return {
                        "name":                 row.get("name", ""),
                        "description":          row.get("about", "") or row.get("full_description", ""),
                        "employee_count":       emp_count,
                        "total_funding_usd":    total_funding,
                        "last_funding_type":    fund_type,
                        "last_funding_date":    fund_date,
                        "industry":             industry,
                        "country":              country,
                        "city":                 location,
                        "homepage_url":         row.get("website", ""),
                        "tech_stack":           tech_list[:10],
                        "has_leadership_hire":  has_leadership_hire,
                        "has_layoff_inline":    has_layoff_inline,
                        "cb_rank":              row.get("cb_rank", ""),
                        "num_employees_raw":    row.get("num_employees", ""),
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

def _check_github_org(company_name: str, homepage_url: str = "") -> dict:
    """
    Signal 3 (medium weight): Check if company has a public GitHub org with
    AI/ML repos. Uses GitHub public API (no auth, 60 req/hr unauthenticated).
    Falls back to org page HTML scan if API returns 404.

    Returns {"found": bool, "evidence": str, "url": str, "ai_repos": list}
    """
    AI_REPO_KEYWORDS = {
        "ml", "ai", "model", "nlp", "vision", "neural", "llm", "data",
        "deep-learning", "machine-learning", "pytorch", "tensorflow", "transformer",
        "mlops", "inference", "embedding", "recommender",
    }

    # Derive GitHub org slug from company name or domain
    slugs = []
    slug_from_name = company_name.lower().replace(" ", "").replace(",", "").replace(".", "")
    slugs.append(slug_from_name)
    if homepage_url:
        domain = homepage_url.replace("https://", "").replace("http://", "").split("/")[0]
        domain_slug = domain.split(".")[0]
        if domain_slug not in slugs:
            slugs.append(domain_slug)

    for slug in slugs:
        api_url = f"https://api.github.com/orgs/{slug}/repos?per_page=100&sort=updated"
        try:
            resp = requests.get(
                api_url, timeout=8,
                headers={"Accept": "application/vnd.github+json", "User-Agent": "signal-enrichment/1.0"}
            )
            if resp.status_code == 200:
                repos = resp.json()
                ai_repos = [
                    r["name"] for r in repos
                    if any(
                        kw in (r.get("name") or "").lower() or
                        kw in (r.get("description") or "").lower()
                        for kw in AI_REPO_KEYWORDS
                    )
                ]
                if ai_repos:
                    return {
                        "found": True,
                        "evidence": f"GitHub org '{slug}' has {len(ai_repos)} AI/ML repos: {ai_repos[:3]}",
                        "url": f"https://github.com/{slug}",
                        "ai_repos": ai_repos[:5],
                        "source": "github_api",
                    }
                return {
                    "found": True,
                    "evidence": f"GitHub org '{slug}' exists ({len(repos)} public repos, none AI/ML-named)",
                    "url": f"https://github.com/{slug}",
                    "ai_repos": [],
                    "source": "github_api",
                }
            if resp.status_code == 404:
                continue  # try next slug
        except Exception:
            continue

    return {"found": False, "evidence": "No public GitHub org found via API", "url": "", "ai_repos": []}


def _check_named_ai_leadership(crunchbase: dict) -> dict:
    """
    Signal 2 (high weight): Detect named AI/ML leadership from Crunchbase
    employee data. Searches current_employees and full_description fields.

    Returns {"found": bool, "title": str, "evidence": str}
    """
    ai_titles = [
        "head of ai", "vp of ai", "vp ai", "chief ai", "chief scientist",
        "vp data", "head of data", "vp machine learning", "director of ai",
        "director of machine learning", "director of data science",
        "chief data officer", "cdo", "chief ml", "vp research",
        "head of research", "applied science", "ai lead", "ml lead",
    ]

    # Check current_employees JSON field
    raw_employees = crunchbase.get("current_employees", "")
    if raw_employees and raw_employees not in ("null", "[]", ""):
        try:
            employees = json.loads(raw_employees)
            for emp in (employees if isinstance(employees, list) else []):
                title = (emp.get("title") or emp.get("role") or "").lower()
                name  = emp.get("name") or emp.get("first_name", "")
                if any(t in title for t in ai_titles):
                    return {"found": True, "title": title, "evidence": f"Named AI leader: {name} ({title})"}
        except Exception:
            pass

    # Fallback: scan full_description for AI leadership mentions
    desc = (crunchbase.get("description", "") + " " + crunchbase.get("full_description", "")).lower()
    for title_kw in ai_titles:
        if title_kw in desc:
            return {"found": True, "title": title_kw, "evidence": f"AI leadership mentioned in profile: '{title_kw}'"}

    return {"found": False, "title": "", "evidence": "No named AI/ML leadership found in public profile"}


def _check_executive_commentary(crunchbase: dict, company_name: str = "") -> dict:
    """
    Signal 4 (medium weight): Detect executive commentary about AI.

    Two-stage search:
    1. Static: Crunchbase full_description, overview_highlights, news fields.
    2. Live: NewsAPI free tier (100 req/day) — searches company + AI keywords
       in last 30 days. Requires NEWS_API_KEY env var; skipped if absent.

    Returns {"found": bool, "evidence": str, "source": str}
    """
    ai_exec_phrases = [
        "ai strategy", "ai-first", "artificial intelligence strategy",
        "investing in ai", "ai transformation", "machine learning strategy",
        "ai roadmap", "our ai", "llm", "generative ai", "ai initiative",
        "ai capabilities", "ai platform", "ai infrastructure",
    ]

    # Stage 1: static Crunchbase fields
    sources = [
        crunchbase.get("full_description", ""),
        crunchbase.get("overview_highlights", ""),
        crunchbase.get("news", ""),
    ]
    combined = " ".join(s for s in sources if s and s not in ("null", "[]", "")).lower()
    hits = [p for p in ai_exec_phrases if p in combined]
    if hits:
        return {"found": True, "evidence": f"Executive/strategic AI commentary in Crunchbase: {hits[:2]}", "source": "crunchbase_fields"}

    # Stage 2: NewsAPI live search (requires NEWS_API_KEY)
    news_api_key = os.getenv("NEWS_API_KEY", "")
    if news_api_key and company_name:
        try:
            query = f"{company_name} artificial intelligence"
            url = (
                f"https://newsapi.org/v2/everything"
                f"?q={requests.utils.quote(query)}"
                f"&sortBy=publishedAt&pageSize=3&language=en"
                f"&apiKey={news_api_key}"
            )
            resp = requests.get(url, timeout=8)
            if resp.status_code == 200:
                articles = resp.json().get("articles", [])
                if articles:
                    title = articles[0].get("title", "")
                    return {
                        "found": True,
                        "evidence": f"Recent news: '{title[:100]}'",
                        "source": "newsapi",
                    }
        except Exception:
            pass  # NewsAPI failure is non-fatal

    return {"found": False, "evidence": "No executive AI commentary found in public records", "source": "none"}


def score_ai_maturity(crunchbase: dict, open_roles: int = 0) -> dict:
    """
    Score AI maturity 0–3 using six signal inputs weighted by tier:

    HIGH weight (+2 points each):
      1. AI-adjacent open roles (via open_roles param from job scraper)
      2. Named AI/ML leadership (Head of AI, VP Data, Chief Scientist)

    MEDIUM weight (+1 point each):
      3. AI industry classification (Crunchbase industry field)
      4. Public GitHub org with AI/ML repo activity
      5. Executive/strategic AI commentary (description, news, highlights)

    LOW weight (+0.5 points each, rounded):
      6. Modern data/ML stack (BuiltWith tech stack)

    Confidence reflects signal weight quality, not just count.
    Score 0 when no public signal — absence ≠ proof of absence.
    """
    score_raw = 0.0
    evidence  = []
    low_conf  = []
    per_signal: dict = {}

    industry   = crunchbase.get("industry", "").lower()
    tech_stack = [t.lower() for t in crunchbase.get("tech_stack", [])]
    homepage   = crunchbase.get("homepage_url", "")
    name       = crunchbase.get("name", "")

    # ── Signal 1: AI-adjacent open roles (HIGH weight) ──────────────────
    if open_roles >= 5:
        score_raw += 2.0
        evidence.append(f"Signal 1 (HIGH): {open_roles} AI-adjacent open roles")
        per_signal["open_roles"] = {"value": open_roles, "weight": "high", "fired": True}
    elif open_roles >= 2:
        score_raw += 1.0
        evidence.append(f"Signal 1 (HIGH): {open_roles} open engineering roles (partial)")
        per_signal["open_roles"] = {"value": open_roles, "weight": "high", "fired": "partial"}
    elif open_roles >= 1:
        low_conf.append(f"Signal 1: only {open_roles} open role — weak hiring signal")
        per_signal["open_roles"] = {"value": open_roles, "weight": "high", "fired": False}
    else:
        per_signal["open_roles"] = {"value": 0, "weight": "high", "fired": False}

    # ── Signal 2: Named AI/ML leadership (HIGH weight) ──────────────────
    leadership = _check_named_ai_leadership(crunchbase)
    if leadership["found"]:
        score_raw += 2.0
        evidence.append(f"Signal 2 (HIGH): {leadership['evidence']}")
    else:
        low_conf.append(f"Signal 2: {leadership['evidence']}")
    per_signal["named_ai_leadership"] = {**leadership, "weight": "high"}

    # ── Signal 3: AI industry classification (MEDIUM weight) ────────────
    ai_industries = ["artificial intelligence", "machine learning",
                     "data analytics", "data science", "mlops",
                     "natural language", "computer vision"]
    ind_hits = [ai for ai in ai_industries if ai in industry]
    if ind_hits:
        score_raw += 1.0
        evidence.append(f"Signal 3 (MEDIUM): AI industry: {industry}")
    per_signal["ai_industry"] = {"value": industry, "hits": ind_hits, "weight": "medium", "fired": bool(ind_hits)}

    # ── Signal 4: GitHub org with AI/ML repos (MEDIUM weight) ───────────
    github = _check_github_org(name, homepage)
    if github["found"] and "AI repos" in github["evidence"]:
        score_raw += 1.0
        evidence.append(f"Signal 4 (MEDIUM): {github['evidence']}")
    elif github["found"]:
        low_conf.append(f"Signal 4: {github['evidence']}")
    else:
        low_conf.append(f"Signal 4: {github['evidence']}")
    per_signal["github_activity"] = {**github, "weight": "medium"}

    # ── Signal 5: Executive/strategic AI commentary (MEDIUM weight) ─────
    exec_comm = _check_executive_commentary(crunchbase, company_name=name)
    if exec_comm["found"]:
        score_raw += 1.0
        evidence.append(f"Signal 5 (MEDIUM): {exec_comm['evidence']}")
    else:
        low_conf.append(f"Signal 5: {exec_comm['evidence']}")
    per_signal["executive_commentary"] = {**exec_comm, "weight": "medium"}

    # ── Signal 6: Modern ML/data stack (LOW weight) ──────────────────────
    ml_stack_kw = ["tensorflow", "pytorch", "scikit", "spark", "databricks",
                   "snowflake", "dbt", "ray", "mlflow", "wandb", "weights",
                   "hugging", "openai", "sagemaker", "vertex", "kubeflow"]
    stack_hits = [t for t in tech_stack if any(kw in t for kw in ml_stack_kw)]
    if stack_hits:
        score_raw += 0.5
        evidence.append(f"Signal 6 (LOW): ML tech stack detected: {stack_hits[:3]}")
    per_signal["ml_tech_stack"] = {"value": stack_hits[:5], "weight": "low", "fired": bool(stack_hits)}

    # ── Compute final integer score 0–3 ─────────────────────────────────
    score = min(int(score_raw), 3)

    # ── Confidence: based on weight quality of contributing signals ──────
    high_weight_fired = sum(1 for s in ["open_roles", "named_ai_leadership"]
                            if per_signal.get(s, {}).get("fired") is True)
    medium_weight_fired = sum(1 for k in ["ai_industry", "github_activity", "executive_commentary"]
                              if per_signal.get(k, {}).get("fired") is True)

    if score >= 2 and high_weight_fired >= 1:
        confidence = "high"
    elif score >= 1 and (high_weight_fired >= 1 or medium_weight_fired >= 2):
        confidence = "medium"
    elif score >= 1:
        confidence = "medium"  # score achieved but from weak signals only
    else:
        confidence = "low"

    # ── Score 0 acknowledgement — absence ≠ proof of absence ────────────
    if score == 0:
        evidence.append(
            "Score 0: No public AI signal found. "
            "Note: absence of public signal does not mean absence of AI capability — "
            "many companies keep AI work in private repos or avoid public disclosure."
        )

    return {
        "score":       score,
        "score_raw":   round(score_raw, 2),
        "confidence":  confidence,
        "evidence":    evidence,
        "low_conf":    low_conf,
        "per_signal":  per_signal,
        "scored_at":   datetime.now(timezone.utc).isoformat(),
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
    if fund_type.lower() in ["series_a", "series_b", "series a", "series b", "seed"]:
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

    # Segment 2 — cost restructuring (layoffs ALWAYS override funding pitch)
    if had_layoffs:
        scores["mid_market_restructuring"] += 4
    if 200 <= employees <= 2000:
        scores["mid_market_restructuring"] += 2
    if funding > 30_000_000:
        scores["mid_market_restructuring"] += 1

    # Segment 3 — engineering leadership transition (from Crunchbase leadership_hire field)
    if crunchbase.get("has_leadership_hire"):
        scores["engineering_leadership_transition"] += 4

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

    # Merge layoff signal: layoffs.fyi CSV + inline Crunchbase layoff field
    layoffs = check_layoffs(company_name)
    if not layoffs.get("had_layoffs") and crunchbase.get("has_layoff_inline"):
        layoffs = {
            "had_layoffs":    True,
            "layoff_count":   0,
            "most_recent":    "",
            "percentage_cut": "",
            "signal":         "cost_pressure",
            "source":         "crunchbase_inline",
        }

    # Upgrade leadership_transition from Crunchbase inline field
    if crunchbase.get("has_leadership_hire"):
        print("  Leadership hire detected (Crunchbase inline)")

    # Job-post velocity signal via Playwright (public pages only)
    job_signal: dict = {}
    if scrape_jobs:
        try:
            from enrichment.job_post_scraper import scrape_job_posts
            job_signal = scrape_job_posts(
                company_name,
                careers_url=careers_url,
                website=crunchbase.get("website", ""),
            )
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

    _now = datetime.now(timezone.utc).isoformat()

    brief = {
        "company_name":       company_name,
        "enriched_at":        _now,
        "firmographics":      crunchbase,

        # ── Per-signal blocks with timestamps + source attribution ──────
        "signals": {
            "crunchbase_funding": {
                "value":       crunchbase.get("last_funding_type", ""),
                "date":        crunchbase.get("last_funding_date", ""),
                "amount_usd":  crunchbase.get("total_funding_usd", 0),
                "confidence":  "high" if crunchbase.get("last_funding_date") else "low",
                "source":      "crunchbase_odm",
                "checked_at":  _now,
            },
            "layoffs": {
                **layoffs,
                "source":     layoffs.get("source", "layoffs_fyi_csv"),
                "checked_at": _now,
            },
            "job_posts": {
                **(job_signal if job_signal else {}),
                "source":     "playwright_public_scrape",
                "checked_at": _now,
                "confidence": job_signal.get("confidence", "low") if job_signal else "low",
                "evidence":   job_signal.get("evidence", "Job scraping skipped.") if job_signal else "Job scraping skipped.",
            },
            "leadership_change": {
                "has_leadership_hire": crunchbase.get("has_leadership_hire", False),
                "source":              "crunchbase_leadership_hire_field",
                "confidence":          "medium" if crunchbase.get("has_leadership_hire") else "low",
                "checked_at":          _now,
            },
            "ai_maturity": {
                **ai_maturity,
                "source":      "enrichment_pipeline_v2",
                "checked_at":  ai_maturity.get("scored_at", _now),
            },
        },

        # ── Flat convenience fields (backwards-compatible) ─────────────
        "layoff_signal":      layoffs,
        "open_roles_count":   open_roles,
        "ai_maturity_score":  ai_maturity["score"],
        "ai_maturity_conf":   ai_maturity["confidence"],
        "ai_evidence":        ai_maturity["evidence"],
        "ai_per_signal":      ai_maturity.get("per_signal", {}),
        "segment":            seg,
        "segment_confidence": segment["confidence"],
        "send_generic_email": segment["send_generic"],
        "all_segment_scores": segment["all_scores"],
        "pitch_angle":        pitch_angle,
        "summary":            summary,

        # ── Legacy job-post block (kept for email_handler compatibility) ─
        "hiring_signal_brief": {
            **(job_signal if job_signal else {}),
            "confidence": job_signal.get("confidence", "low") if job_signal else "low",
            "evidence":   job_signal.get("evidence", "Job scraping skipped or returned no data.") if job_signal else "Job scraping skipped.",
            "source":     "playwright_public_scrape",
            "checked_at": _now,
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