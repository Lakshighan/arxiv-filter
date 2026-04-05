"""
arXiv RSS Filter
Fetches papers from specified arXiv feeds, filters them using Claude,
and writes a filtered RSS feed to docs/feed.xml for GitHub Pages.
"""

import feedparser
import anthropic
import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RESEARCH_INTERESTS = """
I am a PhD student working in astro-statistics. My research has two main avenues:

1. Uncertainty quantification in inverse imaging problems — specifically weak 
   gravitational lensing and mass mapping. This involves Bayesian inference, 
   regularisation, score-based methods, diffusion models, normalising flows, 
   and deep learning approaches to imaging inverse problems.

2. Bayesian evidence computation — primarily using nested sampling algorithms 
   (e.g. MultiNest, PolyChord, nautilus) for model comparison in cosmological 
   contexts.

My broader interests include: MCMC and Langevin sampling methods, variational 
inference, simulation-based inference (likelihood-free inference), machine 
learning for cosmology, field-level inference, CMB analysis, large-scale 
structure, and state-of-the-art Bayesian and ML methodology with applications 
beyond cosmology.
"""

# Feeds to monitor without pre-filtering (lower volume)
FEEDS_FULL = [
    "https://arxiv.org/rss/astro-ph.CO",
    "https://arxiv.org/rss/astro-ph.IM",
    "https://arxiv.org/rss/stat.ML",
]

# Feeds to monitor with keyword pre-filtering (high volume)
FEEDS_PREFILTERED = [
    "https://arxiv.org/rss/cs.LG",
]

# Keywords for pre-filtering high-volume feeds (title must contain at least one)
PREFILTER_KEYWORDS = [
    "bayesian",
    "uncertainty",
    "inverse problem",
    "inverse imaging",
    "sampling",
    "nested sampling",
    "normalising flow",
    "normalizing flow",
    "diffusion model",
    "score-based",
    "score based",
    "variational inference",
    "simulation-based inference",
    "likelihood-free",
    "posterior",
    "mcmc",
    "langevin",
    "denoising",
    "ill-posed",
    "regularisation",
    "regularization",
    "imaging",
    "cosmolog",
    "gravitational lensing",
    "evidence",
    "model comparison",
]

# Minimum relevance score (1-5) to include a paper
MIN_SCORE = 3

# Output file path (served via GitHub Pages)
OUTPUT_FILE = "docs/feed.xml"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def prefilter(title: str, abstract: str) -> bool:
    """Return True if the paper passes the keyword pre-filter."""
    text = (title + " " + abstract).lower()
    return any(kw in text for kw in PREFILTER_KEYWORDS)


def assess_paper(client: anthropic.Anthropic, title: str, abstract: str) -> dict:
    """Ask Claude to assess the relevance of a paper. Returns dict with keys:
    relevant (bool), score (int 1-5), reason (str), suggested_tags (list[str])."""
    prompt = f"""You are filtering arXiv papers for a PhD researcher in astro-statistics.

Researcher profile:
{RESEARCH_INTERESTS}

Paper title: {title}
Abstract: {abstract}

Assess this paper's relevance. Respond ONLY with valid JSON, no other text:
{{
  "relevant": true or false,
  "score": integer from 1 (irrelevant) to 5 (highly relevant),
  "reason": "one concise sentence explaining your assessment",
  "suggested_tags": ["list", "of", "2-4", "short", "topic", "tags"]
}}"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}]
    )

    try:
        return json.loads(response.content[0].text)
    except json.JSONDecodeError:
        # Fallback if JSON parsing fails
        return {"relevant": False, "score": 0, "reason": "Parse error", "suggested_tags": []}


def fetch_feed(url: str, use_prefilter: bool = False) -> list[dict]:
    """Fetch and parse an RSS feed, returning a list of paper dicts."""
    feed = feedparser.parse(url)
    papers = []
    for entry in feed.entries:
        title = entry.get("title", "").replace("\n", " ").strip()
        abstract = entry.get("summary", "").replace("\n", " ").strip()
        link = entry.get("link", "")

        # Parse published date
        try:
            published = parsedate_to_datetime(entry.get("published", ""))
        except Exception:
            published = datetime.now(timezone.utc)

        if use_prefilter and not prefilter(title, abstract):
            continue

        papers.append({
            "title": title,
            "abstract": abstract,
            "link": link,
            "published": published,
        })

    return papers


def build_rss(relevant_papers: list[dict]) -> str:
    """Build an RSS 2.0 XML string from a list of relevant paper dicts."""
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = "Filtered arXiv Feed"
    ET.SubElement(channel, "link").text = "https://arxiv.org"
    ET.SubElement(channel, "description").text = (
        "LLM-filtered arXiv papers relevant to my research interests."
    )
    ET.SubElement(channel, "lastBuildDate").text = (
        datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    )

    for paper in relevant_papers:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = paper["title"]
        ET.SubElement(item, "link").text = paper["link"]
        ET.SubElement(item, "description").text = (
            f"<p><strong>Relevance:</strong> {paper['score']}/5 — {paper['reason']}</p>"
            f"<p><strong>Tags:</strong> {', '.join(paper['suggested_tags'])}</p>"
            f"<p>{paper['abstract']}</p>"
        )
        ET.SubElement(item, "guid").text = paper["link"]
        ET.SubElement(item, "pubDate").text = (
            paper["published"].strftime("%a, %d %b %Y %H:%M:%S +0000")
        )

    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ")
    return ET.tostring(rss, encoding="unicode", xml_declaration=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable not set.")

    client = anthropic.Anthropic(api_key=api_key)

    print("Fetching feeds...")
    all_papers = []

    for url in FEEDS_FULL:
        print(f"  {url}")
        all_papers.extend(fetch_feed(url, use_prefilter=False))

    for url in FEEDS_PREFILTERED:
        print(f"  {url} (pre-filtered)")
        all_papers.extend(fetch_feed(url, use_prefilter=True))

    # Deduplicate by link
    seen = set()
    unique_papers = []
    for p in all_papers:
        if p["link"] not in seen:
            seen.add(p["link"])
            unique_papers.append(p)

    print(f"\n{len(unique_papers)} papers to assess after pre-filtering.")

    relevant_papers = []
    for i, paper in enumerate(unique_papers):
        print(f"  [{i+1}/{len(unique_papers)}] {paper['title'][:80]}...")
        result = assess_paper(client, paper["title"], paper["abstract"])

        if result.get("relevant") and result.get("score", 0) >= MIN_SCORE:
            paper["score"] = result["score"]
            paper["reason"] = result["reason"]
            paper["suggested_tags"] = result.get("suggested_tags", [])
            relevant_papers.append(paper)
            print(f"    ✓ Score {result['score']}/5 — {result['reason']}")
        else:
            print(f"    ✗ Score {result.get('score', 0)}/5")

    print(f"\n{len(relevant_papers)} relevant papers found.")

    # Write RSS output
    os.makedirs("docs", exist_ok=True)
    rss_content = build_rss(relevant_papers)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(rss_content)

    print(f"Feed written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
