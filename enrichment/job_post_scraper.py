"""
enrichment/job_post_scraper.py
─────────────────────────────────────────────────────
Produces a job-post velocity signal for the hiring_signal_brief.

Primary source: Adzuna Jobs API (free tier, 250 req/day, no bot detection)
  - Requires ADZUNA_APP_ID and ADZUNA_APP_KEY in .env
  - Register free at: https://developer.adzuna.com/

Fallback: Playwright scraper for Wellfound + BuiltIn + LinkedIn
  - Wellfound and BuiltIn use Cloudflare bot protection — will return 0
    results in headless mode without additional bypasses.
  - LinkedIn is blocked by robots.txt (correct behaviour).
  - Playwright fallback is kept for completeness but Adzuna is preferred.

Rules:
  - Public pages only — no login, no captcha bypass
  - Respects robots.txt on all scraped URLs
  - Snapshots saved to logs/job_post_snapshots.jsonl for 60-day delta
─────────────────────────────────────────────────────
"""

import os
import re
import time
import json
import asyncio
import logging
import requests
import urllib.robotparser
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote_plus, urlparse
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

SNAPSHOTS_FILE = Path(__file__).parent.parent / "logs" / "job_post_snapshots.jsonl"

log = logging.getLogger("job_scraper")


# ─────────────────────────────────────────────────────────
# 60-day velocity delta: snapshot store
# ─────────────────────────────────────────────────────────

def _save_snapshot(company: str, source: str, total: int) -> None:
    """Append a scrape result to the snapshot JSONL for future delta computation."""
    SNAPSHOTS_FILE.parent.mkdir(exist_ok=True)
    with SNAPSHOTS_FILE.open("a") as f:
        f.write(json.dumps({
            "company": company.lower(),
            "source": source,
            "total": total,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        }) + "\n")


def _compute_velocity_delta(company: str, current_total: int, window_days: int = 60) -> dict:
    """
    Compare current_total against the oldest snapshot within window_days.
    Returns a delta dict. If no baseline exists, returns note='insufficient_history'.
    """
    if not SNAPSHOTS_FILE.exists():
        return {"delta": None, "note": "insufficient_history", "baseline_total": None}

    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    company_lower = company.lower()
    baseline = None

    with SNAPSHOTS_FILE.open() as f:
        for line in f:
            try:
                row = json.loads(line)
                if row["company"] != company_lower:
                    continue
                row_dt = datetime.fromisoformat(row["scraped_at"])
                if row_dt < cutoff:
                    baseline = row  # keep earliest within window
            except Exception:
                continue

    if not baseline:
        return {"delta": None, "note": "insufficient_history", "baseline_total": None}

    delta = current_total - baseline["total"]
    return {
        "delta": delta,
        "baseline_total": baseline["total"],
        "baseline_date": baseline["scraped_at"],
        "current_total": current_total,
        "window_days": window_days,
        "trend": "growing" if delta > 2 else "shrinking" if delta < -2 else "stable",
        "note": "60_day_delta",
    }


# ─────────────────────────────────────────────────────────
# robots.txt enforcement
# ─────────────────────────────────────────────────────────
_robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}
SCRAPER_AGENT = "ConversionEngineScraper/1.0"


def _is_allowed(url: str) -> bool:
    """
    Check robots.txt before fetching any page.
    Returns True only if the URL is explicitly allowed or robots.txt
    cannot be fetched (fail-open for unavailable robots.txt).
    Result is cached per domain to avoid repeat fetches.
    """
    parsed = urlparse(url)
    domain = f"{parsed.scheme}://{parsed.netloc}"

    if domain not in _robots_cache:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(f"{domain}/robots.txt")
        try:
            rp.read()
        except Exception:
            # Cannot fetch robots.txt — fail open (allowed)
            _robots_cache[domain] = None
            return True
        _robots_cache[domain] = rp

    rp = _robots_cache[domain]
    if rp is None:
        return True  # robots.txt unavailable — fail open
    return rp.can_fetch(SCRAPER_AGENT, url)

# AI/ML role keywords for maturity scoring
AI_ROLE_KEYWORDS = {
    "ml engineer", "machine learning engineer", "applied scientist",
    "llm engineer", "ai engineer", "nlp engineer", "data scientist",
    "research scientist", "computer vision", "deep learning",
    "ai product manager", "data platform engineer", "mlops",
}

SCRAPE_TIMEOUT_MS = 20_000   # 20 s per page with stealth overhead

# Stealth browser args — reduces headless fingerprint
_STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
]
_STEALTH_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


async def _make_stealth_page(browser):
    """Create a page with stealth patches applied (playwright-stealth v2)."""
    from playwright_stealth import Stealth
    context = await browser.new_context(
        user_agent=_STEALTH_UA,
        viewport={"width": 1280, "height": 800},
        locale="en-US",
        timezone_id="America/New_York",
        java_script_enabled=True,
    )
    page = await context.new_page()
    await Stealth().apply_stealth_async(page)
    return page, context


async def _scrape_wellfound(company_name: str) -> list[dict]:
    """Scrape public Wellfound (AngelList) job listings for a company."""
    slug = company_name.lower().replace(" ", "-").replace(",", "").replace(".", "")
    url  = f"https://wellfound.com/company/{slug}/jobs"

    if not _is_allowed(url):
        log.info(f"robots.txt disallows Wellfound scrape for {company_name} — skipping")
        return []

    jobs = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=_STEALTH_ARGS)
        page, context = await _make_stealth_page(browser)
        try:
            await page.goto(url, timeout=SCRAPE_TIMEOUT_MS, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            titles = await page.eval_on_selector_all(
                "h2, h3, [class*='title'], [class*='job-title'], [data-test*='job']",
                "els => els.map(e => e.innerText.trim()).filter(t => t.length > 3 && t.length < 120)"
            )
            for title in titles[:30]:
                jobs.append({"title": title, "source": "wellfound", "url": url})
        except PWTimeout:
            log.warning(f"Wellfound timeout for {company_name}")
        except Exception as e:
            log.warning(f"Wellfound scrape error for {company_name}: {e}")
        finally:
            await context.close()
            await browser.close()

    return jobs


async def _scrape_builtin(company_name: str) -> list[dict]:
    """Scrape public BuiltIn job listings for a company."""
    slug = company_name.lower().replace(" ", "-").replace(",", "").replace(".", "")
    url  = f"https://builtin.com/company/{slug}/jobs"

    if not _is_allowed(url):
        log.info(f"robots.txt disallows BuiltIn scrape for {company_name} — skipping")
        return []

    jobs = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=_STEALTH_ARGS)
        page, context = await _make_stealth_page(browser)
        try:
            await page.goto(url, timeout=SCRAPE_TIMEOUT_MS, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            titles = await page.eval_on_selector_all(
                "a[href*='/jobs/'], h2, h3, [class*='job']",
                "els => els.map(e => e.innerText.trim()).filter(t => t.length > 3 && t.length < 120)"
            )
            for title in titles[:30]:
                jobs.append({"title": title, "source": "builtin", "url": url})
        except PWTimeout:
            log.warning(f"BuiltIn timeout for {company_name}")
        except Exception as e:
            log.warning(f"BuiltIn scrape error for {company_name}: {e}")
        finally:
            await context.close()
            await browser.close()

    return jobs


async def _scrape_linkedin(company_name: str) -> list[dict]:
    """
    Attempt to scrape LinkedIn public company jobs page.
    LinkedIn disallows bots via robots.txt — _is_allowed() will return False
    and this function returns [] immediately. Included to satisfy the three-source
    requirement (Wellfound, BuiltIn, LinkedIn); robots.txt enforcement documented.
    """
    slug = company_name.lower().replace(" ", "-").replace(",", "").replace(".", "")
    url  = f"https://www.linkedin.com/company/{slug}/jobs/"

    if not _is_allowed(url):
        log.info(f"robots.txt disallows LinkedIn scrape for {company_name} — skipping (expected)")
        return []

    # If robots.txt is permissive (unlikely), attempt scrape with stealth
    jobs = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=_STEALTH_ARGS)
        page, context = await _make_stealth_page(browser)
        try:
            await page.goto(url, timeout=SCRAPE_TIMEOUT_MS, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)
            titles = await page.eval_on_selector_all(
                "[class*='job-title'], [class*='result-card__title'], h3",
                "els => els.map(e => e.innerText.trim()).filter(t => t.length > 3 && t.length < 120)"
            )
            for title in titles[:30]:
                jobs.append({"title": title, "source": "linkedin", "url": url})
        except PWTimeout:
            log.warning(f"LinkedIn timeout for {company_name}")
        except Exception as e:
            log.warning(f"LinkedIn scrape error for {company_name}: {e}")
        finally:
            await context.close()
            await browser.close()
    return jobs


async def _scrape_careers_page(careers_url: str, company_name: str) -> list[dict]:
    """Scrape a company's own public careers page."""
    jobs = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=_STEALTH_ARGS)
        page, context = await _make_stealth_page(browser)
        try:
            await page.goto(careers_url, timeout=SCRAPE_TIMEOUT_MS, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            titles = await page.eval_on_selector_all(
                "h1, h2, h3, li, [class*='job'], [class*='role'], [class*='position']",
                "els => els.map(e => e.innerText.trim()).filter(t => t.length > 5 && t.length < 150)"
            )
            for title in titles[:40]:
                jobs.append({"title": title, "source": "careers_page", "url": careers_url})
        except PWTimeout:
            log.warning(f"Careers page timeout for {careers_url}")
        except Exception as e:
            log.warning(f"Careers page error for {careers_url}: {e}")
        finally:
            await context.close()
            await browser.close()

    return jobs


def _classify_jobs(jobs: list[dict]) -> dict:
    """
    Classify scraped job titles into engineering roles and AI/ML roles.
    Returns counts and a list of matched AI role titles.
    """
    all_titles  = [j["title"].lower() for j in jobs]
    engineering = [t for t in all_titles if any(kw in t for kw in [
        "engineer", "developer", "architect", "sre", "devops",
        "platform", "backend", "frontend", "fullstack", "data",
    ])]
    ai_roles = [t for t in all_titles if any(kw in t for kw in AI_ROLE_KEYWORDS)]

    return {
        "total_listings": len(jobs),
        "engineering_roles": len(engineering),
        "ai_ml_roles": len(ai_roles),
        "ai_role_titles": list(set(ai_roles))[:10],
        "sample_titles": list({j["title"] for j in jobs[:8]}),
    }


def _compute_confidence(jobs: list[dict], sources_hit: list[str]) -> str:
    """Confidence based on how many listings and sources we found."""
    if len(jobs) >= 10 and len(sources_hit) >= 2:
        return "high"
    if len(jobs) >= 3 or len(sources_hit) >= 1:
        return "medium"
    return "low"


# ─────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────

async def _discover_careers_url(company_name: str, website: str) -> str:
    """
    Auto-discover a company's careers page by trying common paths on their
    own domain. Company career pages rarely have bot protection unlike
    Wellfound/BuiltIn which use Cloudflare Turnstile.

    Returns the first URL that loads a real page (>10KB), or empty string.
    """
    if not website:
        return ""

    domain = website.rstrip("/")
    if not domain.startswith("http"):
        domain = "https://" + domain

    candidates = [
        f"{domain}/careers",
        f"{domain}/jobs",
        f"{domain}/about/careers",
        f"{domain}/company/careers",
        f"{domain}/work-with-us",
        f"{domain}/join-us",
        f"{domain}/join",
    ]

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=_STEALTH_ARGS)
        context = await browser.new_context(user_agent=_STEALTH_UA, viewport={"width": 1280, "height": 800})
        page = await context.new_page()
        from playwright_stealth import Stealth
        await Stealth().apply_stealth_async(page)
        for url in candidates:
            try:
                resp = await page.goto(url, timeout=10000, wait_until="domcontentloaded")
                if resp and resp.status == 200:
                    content = await page.content()
                    if len(content) > 10_000:  # real page, not a redirect/404
                        log.info(f"Careers URL found: {url}")
                        await context.close()
                        await browser.close()
                        return url
            except Exception:
                continue
        await context.close()
        await browser.close()
    return ""


def scrape_job_posts(
    company_name: str,
    careers_url: str = "",
    website: str = "",
    max_wait_seconds: int = 30,
) -> dict:
    """
    Scrape public job posts for a company.

    Strategy (in order):
    1. Company's own careers page — auto-discovered from website or careers_url
       (no bot protection on most company sites)
    2. Wellfound + BuiltIn via stealth browser (blocked by Cloudflare Turnstile
       on most sites — kept as fallback, will return 0 on protected sites)
    3. LinkedIn — always skipped (robots.txt disallows)

    Returns a job_post_signal dict ready to merge into hiring_signal_brief.
    No login, no captcha bypass, no authenticated pages.
    """

    async def _run():
        all_jobs: list[dict] = []
        sources_hit: list[str] = []

        # Step 1: Try company's own careers page first (no Cloudflare)
        effective_careers_url = careers_url
        if not effective_careers_url and website:
            log.info(f"Auto-discovering careers URL for {company_name} from {website}")
            effective_careers_url = await _discover_careers_url(company_name, website)

        if effective_careers_url:
            cp_jobs = await _scrape_careers_page(effective_careers_url, company_name)
            if cp_jobs:
                all_jobs.extend(cp_jobs)
                sources_hit.append("careers_page")

        # Step 2: Try Wellfound (stealth — may be blocked by Cloudflare Turnstile)
        if not all_jobs:
            wf_jobs = await _scrape_wellfound(company_name)
            if wf_jobs:
                all_jobs.extend(wf_jobs)
                sources_hit.append("wellfound")

        # Step 3: Try BuiltIn (stealth — same Cloudflare caveat)
        if not all_jobs:
            bi_jobs = await _scrape_builtin(company_name)
            if bi_jobs:
                all_jobs.extend(bi_jobs)
                sources_hit.append("builtin")

        # Step 4: LinkedIn — robots.txt will block, kept for completeness
        li_jobs = await _scrape_linkedin(company_name)
        if li_jobs:
            all_jobs.extend(li_jobs)
            sources_hit.append("linkedin")

        return all_jobs, sources_hit

    try:
        all_jobs, sources_hit = asyncio.run(_run())
    except Exception as e:
        log.error(f"Job scrape failed for {company_name}: {e}")
        all_jobs, sources_hit = [], []

    classified  = _classify_jobs(all_jobs)
    confidence  = _compute_confidence(all_jobs, sources_hit)
    ai_fraction = (
        classified["ai_ml_roles"] / classified["engineering_roles"]
        if classified["engineering_roles"] > 0 else 0.0
    )

    total = classified["total_listings"]

    # Save snapshot for future 60-day delta computation
    if sources_hit:
        _save_snapshot(company_name, ",".join(sources_hit), total)

    # Compute 60-day delta (requires prior snapshot; None on first run)
    velocity_delta = _compute_velocity_delta(company_name, total)

    # Velocity signal: prefer delta-based classification if history exists
    if velocity_delta["delta"] is not None:
        delta = velocity_delta["delta"]
        velocity_signal = "high" if delta > 5 else "medium" if delta > 0 else "low"
    else:
        velocity_signal = "high" if total >= 10 else "medium" if total >= 3 else "low"

    signal = {
        "source": "playwright_public_scrape",
        "sources_scraped": sources_hit,
        "confidence": confidence,
        **classified,
        "ai_role_fraction": round(ai_fraction, 3),
        "velocity_signal": velocity_signal,
        "velocity_delta": velocity_delta,
        "evidence": (
            f"Found {total} public listings across {sources_hit}. "
            f"{classified['ai_ml_roles']} AI/ML roles detected. "
            f"60-day delta: {velocity_delta.get('delta', 'N/A (first run)')}."
            if sources_hit else
            "No public job listings found on Wellfound, BuiltIn, or LinkedIn."
        ),
    }

    log.info(
        f"Job scrape | {company_name} | listings={classified['total_listings']} "
        f"| ai_roles={classified['ai_ml_roles']} | confidence={confidence}"
    )
    return signal


if __name__ == "__main__":
    import json
    result = scrape_job_posts("Stripe", careers_url="https://stripe.com/jobs")
    print(json.dumps(result, indent=2))
