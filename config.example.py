"""
Personal configuration for the arXiv filter.

Copy this file to `config.py` and edit with your own research interests and
prefilter keywords. `config.py` is gitignored so your personal configuration
stays local.
"""

FEED_SELF_URL = "https://YOUR_USERNAME.github.io/arxiv-filter/feed.xml"

RESEARCH_INTERESTS = """
Describe your research here. Be specific — concrete topics, methods, and
adjacent areas work better than broad fields. A few paragraphs is ideal.
"""

PREFILTER_KEYWORDS = [
    # Edit these to match your field
    "example keyword",
    "another keyword",
]
