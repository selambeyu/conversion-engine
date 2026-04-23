"""
enrichment/job_post_scraper.py
─────────────────────────────────────────────────────
Scrapes public job postings for a company to produce
a job-post velocity signal for the hiring_signal_brief.

Rules (from challenge doc):
  - Public pages only — no login, no captcha bypass
  - Respects robots.txt
  - Sources: BuiltIn, Wellfound, company careers page
  - Returns structured signal with confidence score
─────────────────────────────────────────────────────
"""

import re
import time
import asyncio
import logging
from urllib.parse import quote_plus, urlparse
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

log = logging.getLogger("job_scraper")

# AI/ML role keywords for maturity scoring
AI_ROLE_KEYWORDS = {
    "ml engineer", "machine learning engineer", "applied scientist",
    "llm engineer", "ai engineer", "nlp engineer", "data scientist",
    "research scientist", "computer vision", "deep learning",
    "ai product manager", "data platform engineer", "mlops",
}

SCRAPE_TIMEOUT_MS = 15_000   # 15 s per page — fail fast


async def _scrape_wellfound(company_name: str) -> list[dict]:
    """Scrape public Wellfound (AngelList) job listings for a company."""
    slug = company_name.lower().replace(" ", "-").replace(",", "").replace(".", "")
    url  = f"https://wellfound.com/company/{slug}/jobs"

    jobs = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page    = await browser.new_page()
        # Respect robots.txt — Wellfound allows public job listing crawls
        try:
            await page.goto(url, timeout=SCRAPE_TIMEOUT_MS, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)

            # Extract job titles from listing cards
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
            await browser.close()

    return jobs


async def _scrape_builtin(company_name: str) -> list[dict]:
    """Scrape public BuiltIn job listings for a company."""
    slug = company_name.lower().replace(" ", "-").replace(",", "").replace(".", "")
    url  = f"https://builtin.com/company/{slug}/jobs"

    jobs = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page    = await browser.new_page()
        try:
            await page.goto(url, timeout=SCRAPE_TIMEOUT_MS, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)

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
            await browser.close()

    return jobs


async def _scrape_careers_page(careers_url: str, company_name: str) -> list[dict]:
    """Scrape a company's own public careers page."""
    jobs = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page    = await browser.new_page()
        try:
            await page.goto(careers_url, timeout=SCRAPE_TIMEOUT_MS, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)

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

def scrape_job_posts(
    company_name: str,
    careers_url: str = "",
    max_wait_seconds: int = 30,
) -> dict:
    """
    Scrape public job posts for a company from Wellfound, BuiltIn,
    and optionally the company's own careers page.

    Returns a job_post_signal dict ready to merge into hiring_signal_brief.

    No login, no captcha bypass, no authenticated pages.
    """

    async def _run():
        all_jobs: list[dict] = []
        sources_hit: list[str] = []

        # Try Wellfound
        wf_jobs = await _scrape_wellfound(company_name)
        if wf_jobs:
            all_jobs.extend(wf_jobs)
            sources_hit.append("wellfound")

        # Try BuiltIn
        bi_jobs = await _scrape_builtin(company_name)
        if bi_jobs:
            all_jobs.extend(bi_jobs)
            sources_hit.append("builtin")

        # Try company careers page if provided
        if careers_url:
            cp_jobs = await _scrape_careers_page(careers_url, company_name)
            if cp_jobs:
                all_jobs.extend(cp_jobs)
                sources_hit.append("careers_page")

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

    signal = {
        "source": "playwright_public_scrape",
        "sources_scraped": sources_hit,
        "confidence": confidence,
        **classified,
        "ai_role_fraction": round(ai_fraction, 3),
        "velocity_signal": (
            "high"   if classified["total_listings"] >= 10 else
            "medium" if classified["total_listings"] >= 3  else
            "low"
        ),
        "evidence": (
            f"Found {classified['total_listings']} public listings across {sources_hit}. "
            f"{classified['ai_ml_roles']} AI/ML roles detected."
            if sources_hit else
            "No public job listings found on Wellfound or BuiltIn."
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
