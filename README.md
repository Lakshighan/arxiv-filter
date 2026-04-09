# arXiv RSS Filter

Built with Claude.

Fetches arXiv RSS feeds daily, filters papers for relevance using the Claude API, and publishes a filtered RSS feed via GitHub Pages. Designed for subscription in Readwise Reader, with items delivered as direct links to the arXiv PDFs so they ingest as readable documents rather than bookmarks.

## How it works

1. A GitHub Actions workflow runs daily (08:00 UTC) and fetches a configurable set of arXiv RSS feeds.
2. High-volume feeds (e.g. `cs.LG`) are first narrowed by a keyword pre-filter to avoid spending tokens on obviously irrelevant papers.
3. Remaining papers are sent to Claude Haiku in batches, with your research profile provided as a cached system prompt. Claude returns a 1–5 relevance score for each paper.
4. Papers scoring at or above a configurable threshold are written to `docs/feed.xml`, which GitHub Pages serves as your personal RSS feed. Optionally, they are also pushed directly into Readwise Reader via the API.
5. Persisted state files (`seen_ids.json`, `recent_papers.json`, `pushed_to_reader.json`) make the workflow idempotent and safe to re-run.

## A note on configuration and privacy

Your research profile and prefilter keywords live in a `config.py` file that you create yourself. This file is **not** committed to this public template repository — it is listed in `.gitignore`. The expected workflow is:

1. Fork this repo (as **private** if you'd rather not have your research interests publicly visible).
2. In your fork, remove `config.py` from `.gitignore` (or just ignore the ignore) and commit your own `config.py`.
3. The workflow imports `config.py` at runtime. No secrets are needed for configuration.

This keeps the template repo clean and forkable while letting you edit your config with full visibility in a normal text editor.

## Setup Instructions

### 1. Fork this repository

Click **Fork** at the top of the GitHub page. Choose **private** if you'd rather your research interests and keywords not be publicly discoverable — GitHub Pages still works on private repos on free accounts, and your filtered feed will still be publicly accessible at its Pages URL.

Then clone your fork locally:

```bash
git clone https://github.com/YOUR_USERNAME/arxiv-filter.git
cd arxiv-filter
```

### 2. Create your `config.py`

Copy the example and edit:

```bash
cp config.example.py config.py
```

Open `config.py` and fill in:

- **`RESEARCH_INTERESTS`** — a few sentences or paragraphs describing your research. Be specific: concrete topics, methods, and adjacent areas work much better than broad fields. The more focused this is, the better Claude's relevance scoring.
- **`PREFILTER_KEYWORDS`** — case-insensitive substrings used to narrow high-volume feeds before sending to Claude. Prefer specific phrases ("nested sampling") over broad terms ("sampling"), which will let through hundreds of irrelevant papers.
- **`FEED_SELF_URL`** — update to match your Pages URL (see step 4 below).
- **`FEEDS_FULL`** - arXiv feeds to process in full (use for lower-volume categories like `astro-ph.CO`, `stat.ML`).
- **`FEEDS_PREFILTERED`** arXiv feeds to narrow with keywords before sending to Claude (use for high-volume categories like `cs.LG`)

If you forked as private, simply commit `config.py`:

```bash
git add config.py
git commit -m "Add personal config"
git push
```

If you forked as public and still want to commit your config, first remove `config.py` from `.gitignore`, then commit as above. (If you'd rather keep the public fork config-free, you'll need to adapt the workflow — but going private is much simpler.)

### 3. Add your Anthropic API key

- Go to your fork on GitHub
- Click **Settings → Secrets and variables → Actions**
- Click **New repository secret**
- Name: `ANTHROPIC_API_KEY`
- Value: your API key from [console.anthropic.com](https://console.anthropic.com)

### 3b. (Optional) Add your Readwise token for direct Reader push

Instead of (or in addition to) subscribing to the RSS feed, the filter can push papers directly into Readwise Reader's Feed via the API. This is more reliable than RSS polling for low-subscriber personal feeds and usually delivers papers within seconds of each workflow run.

- Get your token from [readwise.io/access_token](https://readwise.io/access_token)
- Add it as a repository secret named `READWISE_TOKEN`
- Papers will appear in Reader's Feed section tagged `arxiv` and `arxiv-filter`

If you skip this step, the filter falls back to writing `feed.xml` only and you'll need to subscribe to that URL in Reader.

### 4. Enable GitHub Pages

- Go to **Settings → Pages**
- Under **Source**, select **Deploy from a branch**
- Branch: `main`, folder: `/docs`
- Click **Save**

GitHub will provision a URL of the form `https://YOUR_USERNAME.github.io/arxiv-filter/`. Update `FEED_SELF_URL` in your `config.py` to match, commit, and push. The first Pages deploy can take a minute or two.

### 5. Trigger a manual run

Before waiting for the daily cron, test the pipeline:

- Go to the **Actions** tab of your fork
- Select **Filter arXiv RSS**
- Click **Run workflow**

Check the run logs to confirm papers were fetched, assessed, and written. Then open your feed URL in a browser to verify the XML is being served.

### 6. Subscribe in Readwise Reader

If you're using the RSS route (no `READWISE_TOKEN`):

- Open Readwise Reader
- Go to **Feed → Add feed**
- Paste your feed URL
- New filtered papers will appear in your Reader inbox daily

If you're using the direct API push, papers will appear in Reader automatically after each workflow run — no subscription needed.

## Customisation

Most of what you'll want to tweak lives in `config.py` (`RESEARCH_INTERESTS`, `PREFILTER_KEYWORDS`, `FEED_SELF_URL`).

Other configuration lives at the top of `filter_arxiv.py`:

- **`MIN_SCORE`** — minimum relevance score (1–5) for a paper to be included. Raise for stricter filtering.
- **`BATCH_SIZE`** — number of papers sent to Claude per API call. Larger batches are cheaper but risk hitting output limits.
- **`MODEL`** — which Claude model to use. Defaults to Haiku 4.5, which is well-suited to this task.
- **`ABSTRACT_CHAR_LIMIT`** — abstracts are truncated before being sent to Claude, to save input tokens.
- **`RECENT_PAPERS_WINDOW_DAYS`** — how long relevant papers stay visible in `feed.xml`.

The daily schedule is set in `.github/workflows/filter.yml`. Adjust the `cron` expression to change when it runs, or add a second schedule for more frequent updates.

## State files

Three small JSON files are committed back to the repo by the workflow after each run:

- **`seen_ids.json`** — prevents Claude from re-assessing papers already processed. 14-day retention window.
- **`recent_papers.json`** — keeps `feed.xml` populated with a rolling window of relevant papers across runs. 7-day retention window.
- **`pushed_to_reader.json`** — prevents duplicate pushes when the Readwise API route is enabled. 30-day retention window.

They have overlapping-but-distinct purposes and should all be left in place. Deleting `seen_ids.json` will force a full re-assessment of whatever's currently in the arXiv RSS window on the next run — useful if you've changed your `RESEARCH_INTERESTS` or `MIN_SCORE` and want the new settings applied immediately.

## Cost

With Claude Haiku 4.5, batched assessment (15 papers per API call), prompt caching on the system prompt, and truncated abstracts, filtering ~150 papers per day costs well under one US cent per day. Exact figures depend on your feeds and profile length; check your usage dashboard at console.anthropic.com after the first week.

You can reduce cost further by tightening the pre-filter keywords, shortening `RESEARCH_INTERESTS`, or lowering `ABSTRACT_CHAR_LIMIT`. You can improve scoring quality (at modest extra cost) by switching `MODEL` to a Sonnet model.

## Troubleshooting

**`ImportError: cannot import name 'RESEARCH_INTERESTS' from 'config'`.** You haven't created `config.py` yet, or it's missing required fields. Copy `config.example.py` to `config.py` and fill it in.

**Feed loads but has no items.** Your first run may have marked every paper as "seen" before the output logic ran successfully. Delete `seen_ids.json` from the repo and trigger a manual run.

**Items stop appearing in Readwise Reader after a change.** Readwise dedupes by RSS `<guid>` (for the RSS route) or by URL (for the API route). If you change how items are generated in a way that should produce "new" items for the same paper, you may need to change the guid suffix in `build_rss` to avoid collisions with items Readwise has already seen.

**Feed validator complains.** Paste your feed URL into [validator.w3.org/feed](https://validator.w3.org/feed/). Most warnings are benign; errors usually point at a malformed `FEED_SELF_URL` or a missing field.

**GitHub Pages serves a 404.** Confirm under Settings → Pages that the source is set to `main` branch, `/docs` folder. The first deploy after enabling can take a couple of minutes.

**Unexpected jump in API costs.** Usually caused by loosening `PREFILTER_KEYWORDS` in a way that lets through many more papers from high-volume feeds. Add a diagnostic print of the per-feed pass-through count and watch the logs; broad terms like `"sampling"`, `"imaging"`, or `"diffusion model"` are the usual culprits.

## Acknowledgements

Built iteratively with Claude. Contributions and forks welcome.
