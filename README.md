# arXiv RSS Filter

Fetches arXiv RSS feeds daily, filters papers using Claude, and publishes a 
filtered RSS feed via GitHub Pages for subscription in Readwise Reader.

## Setup Instructions

### 1. Create a GitHub Repository

- Go to github.com and create a new **private** repository
- Name it something like `arxiv-filter`
- Do not initialise with a README (you will push these files directly)

### 2. Push These Files

From your terminal:

```bash
cd arxiv-filter
git init
git add .
git commit -m "Initial setup"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/arxiv-filter.git
git push -u origin main
```

### 3. Add Your Anthropic API Key

- Go to your repository on GitHub
- Click **Settings → Secrets and variables → Actions**
- Click **New repository secret**
- Name: `ANTHROPIC_API_KEY`
- Value: your Anthropic API key from console.anthropic.com

### 4. Enable GitHub Pages

- Go to **Settings → Pages**
- Under **Source**, select **Deploy from a branch**
- Branch: `main`, folder: `/docs`
- Click **Save**
- GitHub will provide a URL like `https://YOUR_USERNAME.github.io/arxiv-filter/`

### 5. Get Your Feed URL

Your filtered RSS feed will be available at:

```
https://YOUR_USERNAME.github.io/arxiv-filter/feed.xml
```

### 6. Subscribe in Readwise Reader

- Open Readwise Reader
- Go to **Feed** → **Add feed**
- Paste your feed URL
- New filtered papers will appear in your Reader inbox daily

### 7. Trigger a Manual Run (Optional)

To test before the first scheduled run:

- Go to **Actions** tab in your GitHub repository
- Select **Filter arXiv RSS**
- Click **Run workflow**

## Customisation

Edit `filter_arxiv.py` to:

- Add or remove arXiv feeds in `FEEDS_FULL` or `FEEDS_PREFILTERED`
- Adjust `PREFILTER_KEYWORDS` to tune the keyword pre-filter for high-volume feeds
- Update `RESEARCH_INTERESTS` if your focus changes
- Lower or raise `MIN_SCORE` to make filtering more or less strict

## Cost Estimate

Each API call processes one paper abstract (~400 tokens input, ~100 tokens output).
At Claude Sonnet pricing, filtering 150 papers/day costs approximately $0.03-0.05/day.
