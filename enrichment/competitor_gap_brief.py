"""
enrichment/competitor_gap_brief.py
─────────────────────────────────────────────────────
Produces competitor_gap_brief.json for a prospect.

Identifies 5-10 top-quartile competitors in the same sector,
scores their AI maturity from public signals, computes where
the prospect sits in the sector distribution, and extracts
2-3 practices the top quartile shows that the prospect does not.

This converts cold outreach from "Tenacious offers X" to
"three companies in your sector are doing X and you are not."
─────────────────────────────────────────────────────
"""

import os
import csv
import json
import time
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

DATA_DIR       = Path(__file__).parent.parent / "data"
CRUNCHBASE_CSV = DATA_DIR / "crunchbase_sample.csv"
OUTPUT_DIR     = Path(__file__).parent.parent / "data"

DEV_MODEL = os.getenv("DEV_MODEL", "deepseek/deepseek-chat")


# ─────────────────────────────────────────────────────────
# STEP 1 — Find sector peers from Crunchbase data
# ─────────────────────────────────────────────────────────

def load_crunchbase() -> list[dict]:
    if not CRUNCHBASE_CSV.exists():
        return []
    rows = []
    with CRUNCHBASE_CSV.open(encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def find_sector_peers(company_name: str, industry: str, all_companies: list[dict], max_peers: int = 10) -> list[dict]:
    """Return up to max_peers companies in the same industry, excluding the prospect."""
    peers = []
    industry_lower = industry.lower()
    for row in all_companies:
        name = row.get("name", "").strip()
        row_industry = row.get("industry", "").lower()
        if name.lower() == company_name.lower():
            continue
        if industry_lower and industry_lower in row_industry:
            peers.append(row)
        if len(peers) >= max_peers:
            break
    return peers


# ─────────────────────────────────────────────────────────
# STEP 2 — Score AI maturity for each peer
# ─────────────────────────────────────────────────────────

def score_ai_maturity_simple(company: dict) -> dict:
    """
    Quick AI maturity score from available Crunchbase fields.
    0 = no signal, 1 = weak, 2 = moderate, 3 = strong.
    """
    score = 0
    signals = []

    description = (company.get("description") or "").lower()
    industry = (company.get("industry") or "").lower()
    name = company.get("name", "")

    ai_keywords = ["ai", "machine learning", "ml", "artificial intelligence",
                   "deep learning", "llm", "nlp", "neural", "computer vision",
                   "data science", "predictive", "automation", "intelligent"]

    matched = [kw for kw in ai_keywords if kw in description or kw in industry]
    if matched:
        score += min(len(matched), 2)
        signals.append(f"AI keywords in profile: {', '.join(matched[:3])}")

    funding = float(company.get("total_funding_usd") or 0)
    if funding > 50_000_000:
        score += 1
        signals.append(f"Well-funded (${funding/1e6:.0f}M) — likely has data/AI teams")

    score = min(score, 3)
    return {
        "name": name,
        "score": score,
        "confidence": "medium" if score > 0 else "low",
        "signals": signals,
        "industry": company.get("industry", ""),
        "funding_usd": funding,
        "employees": company.get("employee_count", "unknown"),
    }


# ─────────────────────────────────────────────────────────
# STEP 3 — Use AI to extract gap practices
# ─────────────────────────────────────────────────────────

def extract_gap_practices(
    prospect_name: str,
    prospect_score: int,
    top_peers: list[dict],
    industry: str,
) -> list[str]:
    """
    Ask the LLM to identify 2-3 specific AI practices that top-quartile
    peers show publicly but the prospect does not.
    """
    client = OpenAI(
        api_key=os.getenv("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1"
    )

    peers_summary = "\n".join([
        f"- {p['name']}: AI maturity {p['score']}/3, signals: {'; '.join(p['signals'][:2]) or 'limited public signal'}"
        for p in top_peers[:5]
    ])

    prompt = f"""You are a B2B sales researcher analyzing AI adoption in the {industry} sector.

PROSPECT: {prospect_name}
PROSPECT AI MATURITY SCORE: {prospect_score}/3

TOP-QUARTILE SECTOR PEERS:
{peers_summary}

Based only on the signals above, identify 2-3 specific AI practices or capabilities that
the top-quartile companies show publicly but {prospect_name} does not appear to have yet.

Rules:
- Be specific — name the practice, not generic advice
- Only state what you can infer from the data above
- Use hedged language: "appears to", "based on public signals"
- Each practice should be 1-2 sentences max

Format: Return a JSON array of strings, one per practice.
Example: ["Company X appears to have an MLOps function based on job postings for ML engineers.", "..."]"""

    try:
        response = client.chat.completions.create(
            model=DEV_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=400,
        )
        content = response.choices[0].message.content.strip()
        # Extract JSON array
        start = content.find("[")
        end = content.rfind("]") + 1
        if start >= 0 and end > start:
            return json.loads(content[start:end])
    except Exception as e:
        print(f"  [warn] Gap extraction failed: {e}")

    return [
        f"Top-quartile {industry} companies appear to have dedicated AI/ML engineering roles based on public job postings.",
        f"Leading peers show signal of modern data stack adoption (dbt, Snowflake, or similar) not visible in {prospect_name}'s public profile.",
    ]


# ─────────────────────────────────────────────────────────
# STEP 4 — Main function: generate full brief
# ─────────────────────────────────────────────────────────

def generate_competitor_gap_brief(
    prospect_name: str,
    prospect_industry: str,
    prospect_ai_score: int = 1,
    save_to_file: bool = True,
) -> dict:
    """
    Generate a competitor_gap_brief.json for one prospect.

    Returns the brief dict and optionally saves it to data/competitor_gap_brief.json.
    """
    print(f"\nGenerating competitor gap brief for: {prospect_name}")
    print(f"  Industry: {prospect_industry} | AI Maturity: {prospect_ai_score}/3")

    all_companies = load_crunchbase()
    peers_raw = find_sector_peers(prospect_name, prospect_industry, all_companies)

    if not peers_raw:
        print("  [warn] No sector peers found in Crunchbase sample — using fallback")
        peers_raw = [{"name": f"Peer {i+1}", "description": "AI-focused tech company",
                      "industry": prospect_industry, "total_funding_usd": "20000000",
                      "employee_count": "80"} for i in range(3)]

    # Score each peer
    scored_peers = [score_ai_maturity_simple(p) for p in peers_raw]
    scored_peers.sort(key=lambda x: x["score"], reverse=True)

    top_quartile = scored_peers[:3]
    sector_scores = [p["score"] for p in scored_peers]
    sector_mean = sum(sector_scores) / len(sector_scores) if sector_scores else 0

    # Prospect position in sector
    percentile = sum(1 for s in sector_scores if s <= prospect_ai_score) / max(len(sector_scores), 1)

    # Extract gap practices using AI
    print("  Extracting gap practices via AI...")
    gap_practices = extract_gap_practices(
        prospect_name, prospect_ai_score, top_quartile, prospect_industry
    )

    brief = {
        "generated_at": datetime.utcnow().isoformat(),
        "prospect": {
            "name": prospect_name,
            "industry": prospect_industry,
            "ai_maturity_score": prospect_ai_score,
        },
        "sector_analysis": {
            "peers_analyzed": len(scored_peers),
            "sector_mean_ai_score": round(sector_mean, 2),
            "prospect_percentile": round(percentile, 2),
            "prospect_vs_top_quartile": prospect_ai_score - (top_quartile[0]["score"] if top_quartile else 0),
        },
        "top_quartile_peers": top_quartile,
        "gap_practices": gap_practices,
        "outreach_hook": (
            f"{len([p for p in scored_peers if p['score'] >= 2])} companies in your sector "
            f"show strong public AI signal — {prospect_name} appears earlier in that journey. "
            f"Here's what the top tier is doing that you may not be yet."
            if prospect_ai_score < 2
            else
            f"{prospect_name} is ahead of most sector peers on AI maturity. "
            f"The gap practices below represent the next frontier."
        ),
    }

    if save_to_file:
        out_path = OUTPUT_DIR / "competitor_gap_brief.json"
        OUTPUT_DIR.mkdir(exist_ok=True)
        with out_path.open("w") as f:
            json.dump(brief, f, indent=2)
        print(f"  Saved → {out_path}")

    print(f"  Done. {len(gap_practices)} gap practices identified.")
    return brief


if __name__ == "__main__":
    brief = generate_competitor_gap_brief(
        prospect_name="FinEdge",
        prospect_industry="Financial Technology",
        prospect_ai_score=1,
    )
    print(json.dumps(brief, indent=2))
