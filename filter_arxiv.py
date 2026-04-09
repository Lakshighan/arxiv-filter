"""
arXiv RSS Filter
Fetches papers from specified arXiv feeds, filters them using Claude,
and writes a filtered RSS feed to docs/feed.xml for GitHub Pages.
"""

import feedparser
import anthropic
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

FEEDS_FULL = [
    "https://arxiv.org/rss/astro-ph.CO",
    "https://arxiv.org/rss/astro-ph.IM",
    "https://arxiv.org/rss/stat.ML",
    "https://arxiv.org/rss/stat.CO",
    "https://arxiv.org/rss/stat.ME",
]

FEEDS_PREFILTERED = [
    "https://arxiv.org/rss/cs.LG",
    "https://arxiv.org/rss/astro-ph.GA",
    "https://arxiv.org/rss/eess.IV",
    "https://arxiv.org/rss/eess.SP",
    "https://arxiv.org/rss/math.ST",
]

try:
    from config import RESEARCH_INTERESTS, PREFILTER_KEYWORDS, FEED_SELF_URL
except ImportError:
    raise ImportError(
        "config.py not found. Copy config.example.py to config.py and "
        "edit it with your research interests and prefilter keywords."
    )

MIN_SCORE = 3
BATCH_SIZE = 15
ABSTRACT_CHAR_LIMIT = 1000
MODEL = "claude-haiku-4-5-20251001"
OUTPUT_FILE = "docs/feed.xml"
SEEN_IDS_FILE = "seen_ids.json"
SEEN_IDS_MAX_AGE_DAYS = 14  # prune older entries to keep the file small
RECENT_PAPERS_FILE = "recent_papers.json"
RECENT_PAPERS_WINDOW_DAYS = 7  # how long a paper stays in feed.xml

READWISE_API_URL = "https://readwise.io/api/v3/save/"
PUSHED_FILE = "pushed_to_reader.json"
PUSHED_MAX_AGE_DAYS = 30  # prune entries older than this

SYSTEM_PROMPT = f"""You are filtering arXiv papers for a PhD researcher in astro-statistics.

Researcher profile:
{RESEARCH_INTERESTS}

You will be given a numbered list of papers (title + abstract). For each, assess relevance to the profile and return a JSON array of objects, one per paper, in the same order. Each object must have exactly two keys: "id" (the integer index you were given) and "score" (integer 1-5, where 1 is irrelevant and 5 is highly relevant).

Respond with ONLY the JSON array, no prose, no code fences."""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def prefilter(title: str, abstract: str) -> bool:
    text = (title + " " + abstract).lower()
    return any(kw in text for kw in PREFILTER_KEYWORDS)


def truncate(text: str, limit: int = ABSTRACT_CHAR_LIMIT) -> str:
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "..."


def strip_json_fences(text: str) -> str:
    """Remove ```json ... ``` fences if present."""
    text = text.strip()
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    return match.group(1) if match else text


def load_seen_ids() -> dict:
    """Load persisted seen-id map: {link: iso_date_string}."""
    if not os.path.exists(SEEN_IDS_FILE):
        return {}
    try:
        with open(SEEN_IDS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_seen_ids(seen: dict) -> None:
    # Prune old entries
    cutoff = datetime.now(timezone.utc).timestamp() - SEEN_IDS_MAX_AGE_DAYS * 86400
    pruned = {
        link: ds for link, ds in seen.items()
        if datetime.fromisoformat(ds).timestamp() >= cutoff
    }
    with open(SEEN_IDS_FILE, "w", encoding="utf-8") as f:
        json.dump(pruned, f, indent=2, sort_keys=True)

def load_recent_papers() -> list[dict]:
    """Load the rolling window of relevant papers."""
    if not os.path.exists(RECENT_PAPERS_FILE):
        return []
    try:
        with open(RECENT_PAPERS_FILE, "r", encoding="utf-8") as f:
            papers = json.load(f)
        # Rehydrate datetime from ISO string
        for p in papers:
            p["published"] = datetime.fromisoformat(p["published"])
        return papers
    except (json.JSONDecodeError, OSError, KeyError, ValueError):
        return []


def save_recent_papers(papers: list[dict]) -> None:
    """Persist relevant papers, pruning anything older than the window."""
    cutoff = datetime.now(timezone.utc).timestamp() - RECENT_PAPERS_WINDOW_DAYS * 86400
    pruned = [p for p in papers if p["published"].timestamp() >= cutoff]
    # Serialize datetime to ISO string for JSON
    serializable = [
        {**p, "published": p["published"].isoformat()}
        for p in pruned
    ]
    with open(RECENT_PAPERS_FILE, "w", encoding="utf-8") as f:
        json.dump(serializable, f, indent=2, sort_keys=True)

def load_pushed() -> dict:
    """Load the set of papers successfully pushed to Reader: {link: iso_date}."""
    if not os.path.exists(PUSHED_FILE):
        return {}
    try:
        with open(PUSHED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_pushed(pushed: dict) -> None:
    cutoff = datetime.now(timezone.utc).timestamp() - PUSHED_MAX_AGE_DAYS * 86400
    pruned = {
        link: ds for link, ds in pushed.items()
        if datetime.fromisoformat(ds).timestamp() >= cutoff
    }
    with open(PUSHED_FILE, "w", encoding="utf-8") as f:
        json.dump(pruned, f, indent=2, sort_keys=True)


def assess_batch_with_retry(
    client: anthropic.Anthropic, batch: list[dict], max_retries: int = 4
) -> dict[int, int]:
    """Assess a batch of papers. Returns {index: score}. Retries with backoff."""
    user_content = "\n\n".join(
        f"[{i}] Title: {p['title']}\nAbstract: {truncate(p['abstract'])}"
        for i, p in enumerate(batch)
    )

    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=400,
                system=[{
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": user_content}],
            )
            raw = strip_json_fences(response.content[0].text)
            parsed = json.loads(raw)
            return {int(item["id"]): int(item["score"]) for item in parsed}
        except (anthropic.APIError, json.JSONDecodeError, KeyError, ValueError) as e:
            wait = 2 ** attempt
            print(f"    ! batch error ({type(e).__name__}): {e}; retrying in {wait}s")
            time.sleep(wait)

    print("    ! batch failed after retries; marking all as score 0")
    return {i: 0 for i in range(len(batch))}


def fetch_feed(url: str, use_prefilter: bool = False) -> list[dict]:
    feed = feedparser.parse(url)
    papers = []
    for entry in feed.entries:
         title = entry.get("title", "").replace("\n", " ").strip()
         abstract = entry.get("summary", "").replace("\n", " ").strip()
         link = entry.get("link", "")
         pdf_link = link.replace("/abs/", "/pdf/") + ".pdf" if "/abs/" in link else link

         if use_prefilter and not prefilter(title, abstract):
            continue
         
         # Prefer parsed struct_time from feedparser (handles dc:date and pubDate)
         if getattr(entry, "published_parsed", None):
            published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
         elif getattr(entry, "updated_parsed", None):
            published = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
         else:
            published = datetime.now(timezone.utc)
            
         if getattr(entry, "authors", None):
            authors = ", ".join(a.get("name", "").strip() for a in entry.authors if a.get("name"))
         else:
            authors = entry.get("author", "").strip()
            
         authors = authors.replace("\n", " ")
         papers.append({
            "title": title,
            "authors": authors,
            "abstract": abstract,
            "link": link,
            "pdf_link": pdf_link,
            "published": published,
         })

    return papers


def build_rss(relevant_papers: list[dict], feed_self_url: str) -> str:
    rss = ET.Element("rss", {
        "version": "2.0",
        "xmlns:atom": "http://www.w3.org/2005/Atom",
        "xmlns:dc": "http://purl.org/dc/elements/1.1/",
    })
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = "Filtered arXiv Feed"
    ET.SubElement(channel, "link").text = feed_self_url
    ET.SubElement(channel, "description").text = (
        "LLM-filtered arXiv papers relevant to my research interests."
    )
    ET.SubElement(channel, "language").text = "en"
    ET.SubElement(channel, "atom:link", {
        "href": feed_self_url,
        "rel": "self",
        "type": "application/rss+xml",
    })
    ET.SubElement(channel, "lastBuildDate").text = (
        datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    )

    for paper in relevant_papers:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = paper["title"]
        ET.SubElement(item, "link").text = paper["pdf_link"]
        if paper.get("authors"):
            ET.SubElement(item, "dc:creator").text = paper["authors"]
        ET.SubElement(item, "description").text = (
            f"Relevance: {paper['score']}/5\n\n"
            f"Authors: {paper.get('authors', 'Unknown')}\n\n"
            f"Abstract page: {paper['link']}\n\n"
            f"{paper['abstract']}"
        )
        guid = ET.SubElement(item, "guid", {"isPermaLink": "false"})
        guid.text = paper["link"] + "#pdf"
        ET.SubElement(item, "pubDate").text = (
            paper["published"].strftime("%a, %d %b %Y %H:%M:%S +0000")
        )

    ET.indent(ET.ElementTree(rss), space="  ")
    return ET.tostring(rss, encoding="unicode", xml_declaration=True)

def push_to_reader(paper: dict, token: str, max_retries: int = 3) -> bool:
    """Push a single paper to Readwise Reader's Feed. Returns True on success."""
    payload = {
        "url": paper["pdf_link"],
        "title": paper["title"],
        "author": paper.get("authors", "") or "arXiv",
        "summary": (
            f"Relevance: {paper['score']}/5\n\n"
            f"Abstract page: {paper['link']}\n\n"
            f"{paper['abstract']}"
        ),
        "published_date": paper["published"].date().isoformat(),
        "location": "feed",
        "category": "pdf",
        "saved_using": "arxiv-filter",
        "tags": ["arxiv", "arxiv-filter"],
    }

    for attempt in range(max_retries):
        try:
            response = requests.post(
                READWISE_API_URL,
                headers={"Authorization": f"Token {token}"},
                json=payload,
                timeout=30,
            )
            if response.status_code in (200, 201):
                return True
            # 429 = rate limited; back off longer
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", "10"))
                print(f"    ! rate limited; sleeping {retry_after}s")
                time.sleep(retry_after)
                continue
            print(f"    ! push failed ({response.status_code}): {response.text[:200]}")
        except requests.RequestException as e:
            print(f"    ! push error: {e}")
        time.sleep(2 ** attempt)
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable not set.")

    client = anthropic.Anthropic(api_key=api_key)
    seen_ids = load_seen_ids()
    now_iso = datetime.now(timezone.utc).isoformat()

    print("Fetching feeds...")
    all_papers = []
    for url in FEEDS_FULL:
        print(f"  {url}")
        all_papers.extend(fetch_feed(url, use_prefilter=False))
    for url in FEEDS_PREFILTERED:
        print(f"  {url} (pre-filtered)")
        all_papers.extend(fetch_feed(url, use_prefilter=True))

    # Deduplicate within this run AND against persisted seen set
    unique_papers = []
    seen_this_run = set()
    for p in all_papers:
        if p["link"] in seen_this_run or p["link"] in seen_ids:
            continue
        seen_this_run.add(p["link"])
        unique_papers.append(p)

    print(f"\n{len(unique_papers)} new papers to assess "
          f"({len(all_papers) - len(unique_papers)} skipped as duplicates/seen).")

    relevant_papers = []
    for start in range(0, len(unique_papers), BATCH_SIZE):
        batch = unique_papers[start:start + BATCH_SIZE]
        print(f"  assessing batch {start // BATCH_SIZE + 1} "
              f"({len(batch)} papers)")
        scores = assess_batch_with_retry(client, batch)

        for i, paper in enumerate(batch):
            score = scores.get(i, 0)
            # Mark as seen regardless of score, so we don't re-assess tomorrow
            seen_ids[paper["link"]] = now_iso
            if score >= MIN_SCORE:
                paper["score"] = score
                relevant_papers.append(paper)
                print(f"    ✓ [{score}/5] {paper['title'][:70]}")
            else:
                print(f"    ✗ [{score}/5] {paper['title'][:70]}")

        # Persist incrementally so a mid-run crash doesn't lose progress
        save_seen_ids(seen_ids)
    print(f"\n{len(relevant_papers)} newly relevant papers found this run.")

    # Push to Readwise Reader
    readwise_token = os.environ.get("READWISE_TOKEN")
    pushed = load_pushed()
    if readwise_token:
        to_push = [p for p in relevant_papers if p["link"] not in pushed]
        print(f"Pushing {len(to_push)} papers to Readwise Reader...")
        for paper in to_push:
            if push_to_reader(paper, readwise_token):
                pushed[paper["link"]] = now_iso
                print(f"    ✓ pushed: {paper['title'][:70]}")
                save_pushed(pushed)  # incremental save
            else:
                print(f"    ✗ push failed (will retry next run): {paper['title'][:70]}")
    else:
        print("READWISE_TOKEN not set; skipping push to Reader.")

    # Merge with rolling window and rebuild feed.xml (unchanged from before)
    existing = load_recent_papers()
    by_link = {p["link"]: p for p in existing}
    for p in relevant_papers:
        by_link[p["link"]] = p

    merged = list(by_link.values())
    cutoff = datetime.now(timezone.utc).timestamp() - RECENT_PAPERS_WINDOW_DAYS * 86400
    merged = [p for p in merged if p["published"].timestamp() >= cutoff]
    merged.sort(key=lambda p: p["published"], reverse=True)

    save_recent_papers(merged)
    print(f"{len(merged)} papers in rolling {RECENT_PAPERS_WINDOW_DAYS}-day window.")

    os.makedirs("docs", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(build_rss(merged, FEED_SELF_URL))
    print(f"Feed written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
