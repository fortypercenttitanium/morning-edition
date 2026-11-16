# The Morning Edition

A personal digital newspaper: static HTML + CSS, hosted free on GitHub Pages, generated with OpenAI's web-search API and GitHub Actions. No server, Next.js, database, or Node toolchain.

## Quick start — GitHub website only

1. On GitHub, create a **public** repository named `morning-edition` with the default branch `main`.
2. Upload **the contents of this project folder** to the repository, including the hidden `.github` directory and its `workflows/publish.yml` file. Upload the unzipped files, **not the ZIP file itself**. An easy alternative is GitHub Desktop: **File > Add local repository** (initialize Git first if needed), then Publish repository.
3. Open **Settings > Pages > Build and deployment > Source** and select **GitHub Actions**.
4. A sample front page is already in `site/index.html`. On initial push, the workflow should deploy it without needing a paid API key.
5. To enable daily article generation, create an OpenAI API key at https://platform.openai.com/api-keys and add billing / an appropriate budget limit. ChatGPT Plus is billed separately from the OpenAI API.
6. In your GitHub repo go to **Settings > Secrets and variables > Actions > New repository secret**. Name it `OPENAI_API_KEY`; paste your key as its value. Never commit or share the key.
7. Select **Actions > Publish Morning Edition > Run workflow** to generate your first LIVE issue. Check the run logs if it fails; a successful run automatically commits today's edition and deploys the site.
8. In **Settings > Pages**, use **Visit site**. The URL normally resembles `https://YOUR-USERNAME.github.io/morning-edition/`.

From then on, the workflow requests a new issue at **7:35 a.m. America/New_York** daily to target availability by **8:30 a.m.** This is best-effort: GitHub Actions can be delayed or occasionally dropped, and the model's research duration varies. Public repositories have free standard GitHub Actions runners / Pages hosting, but the OpenAI API and web-search tool incur usage-based costs. Check your usage dashboard.

**Important:** GitHub can automatically disable scheduled Actions in public repositories after 60 days with no repository activity. This project normally commits new issues daily, which counts as activity, but still check the Actions tab occasionally if issues stop arriving.

## Editorial controls

- `config/editorial.md`: newspaper priorities and voice.
- `data/history.json`: published story keys/titles so the next edition can avoid repeating the same news.
- `scripts/build.py`: API research/generation, deduplication, archive creation, HTML rendering.
- `site/styles.css`: responsive newspaper design.
- `site/index.html`: latest issue.
- `site/archive.html`: archive links.
- `site/editions/YYYY-MM-DD/index.html`: immutable per-day editions.

## Testing locally (optional)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
# Set OPENAI_API_KEY in your environment, then:
python scripts/build.py
python -m http.server 8000 --directory site
```
Open http://localhost:8000. The first script invocation requires an API key and will create a new issue; do not run it merely to preview the included sample page.

## Reliability notes

- It fetches source evidence using the API's web search tool. Cite URLs in the generated article data; automated HTML rendering escapes untrusted data.
- The model is instructed to use direct news URLs and may still make mistakes. This is a personal prototype, not a fact-checked newsroom. Review disputed/high-stakes claims at the linked sources.
- Story history is a **guardrail**, not a perfect guarantee. Model-generated `story_key` values plus title similarity block many repeats. Genuine new developments can pass when marked `UPDATE` with a `new_development` description.
- An API or generation failure raises an error and **does not overwrite yesterday's issue**.
- Generated pages and story history are committed to the public repository. Never include private info in the editorial configuration or stories.
- API costs are separate. A long paper with live web research can cost more than a simple summary; set a project budget limit in your API account.
- The existing ChatGPT 8:30 AM newspaper automation is separate; this GitHub workflow does not modify or turn it off.
