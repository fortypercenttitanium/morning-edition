#!/usr/bin/env python3
"""Research, deduplicate, render and publish the Morning Edition.

Designed to run in GitHub Actions. No database, no server, no JS framework.

News articles are the model's ORIGINAL summaries of linked reporting, not copies.
The script cannot independently fact-check every generated sentence: sources should
be reviewed when a claim matters. On any generation/validation error, no files change.
"""
from __future__ import annotations

from datetime import datetime
from difflib import SequenceMatcher
from html import escape
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
import json
import os
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'site'
HISTORY = ROOT / 'data' / 'history.json'
EDITORIAL = ROOT / 'config' / 'editorial.md'
TIMEZONE = ZoneInfo('America/New_York')
DATE = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
MODEL = os.environ.get('OPENAI_MODEL', 'gpt-5.4')

STORY_SCHEMA = {
    'type': 'object',
    'properties': {
        'key': {'type': 'string', 'description': 'Stable event/topic identifier, e.g. philly-transit-budget-2026. Reuse existing key for genuine updates.'},
        'category': {'type': 'string'},
        'title': {'type': 'string'},
        'deck': {'type': 'string'},
        'paragraphs': {'type': 'array', 'items': {'type': 'string'}},
        'why': {'type': 'string'},
        'source': {'type': 'string'},
        'url': {'type': 'string'},
        'published': {'type': 'string', 'description': 'Source article publication date YYYY-MM-DD when verified; otherwise empty string'},
        'update_note': {'type': 'string', 'description': 'UPDATE only if substantial new fact since last issue; otherwise empty string'},
        'new_development': {'type': 'string', 'description': 'Explain the specific new development since prior report for UPDATE; otherwise empty string'},
    },
    'required': ['key', 'category', 'title', 'deck', 'paragraphs', 'why', 'source', 'url', 'published', 'update_note', 'new_development'],
    'additionalProperties': False,
}
LONG_READ_SCHEMA = {
    'type': 'object',
    'properties': {
        'title': {'type': 'string'},
        'description': {'type': 'string'},
        'source': {'type': 'string'},
        'url': {'type': 'string'},
    },
    'required': ['title', 'description', 'source', 'url'],
    'additionalProperties': False,
}
SCHEMA = {
    'type': 'object',
    'properties': {
        'date': {'type': 'string'},
        'lead': STORY_SCHEMA,
        'sections': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string'},
                    'stories': {'type': 'array', 'items': STORY_SCHEMA},
                },
                'required': ['name', 'stories'],
                'additionalProperties': False,
            },
        },
        'long_reads': {'type': 'array', 'items': LONG_READ_SCHEMA},
    },
    'required': ['date', 'lead', 'sections', 'long_reads'],
    'additionalProperties': False,
}


def safe(value: object) -> str:
    return escape(str(value or ''), quote=True)


def valid_url(url: str) -> bool:
    """Accept plausible direct HTTPS article links, never placeholders or homepages."""
    if not isinstance(url, str) or not url or any(char.isspace() for char in url):
        return False
    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or '').lower()
    except ValueError:
        return False
    if parsed.scheme != 'https' or '.' not in hostname or parsed.username or parsed.password:
        return False
    if hostname in {'example.com', 'example.org', 'example.net'} or hostname.endswith('.example'):
        return False
    return bool(parsed.path.strip('/')) or bool(parsed.query)


def url_link(url: str, label: str) -> str:
    if not valid_url(url):
        return ''
    return f'<a target="_blank" rel="noopener noreferrer" href="{safe(url)}">{safe(label)}</a>'


def compact_key(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-')[:120]


def normalize_title(value: str) -> str:
    words = re.findall(r'[a-z0-9]+', value.lower())
    stopwords = {'the','a','an','in','of','to','for','and','is','on','as','with','after','about','how','why','new','latest','today','at'}
    return ' '.join(w for w in words if w not in stopwords)


def meaningful_update(story: dict) -> bool:
    return story.get('update_note', '').strip().upper() == 'UPDATE' and len(story.get('new_development', '').strip()) >= 35


def too_similar(story: dict, previous: list[dict]) -> bool:
    key = compact_key(story['key'])
    title = normalize_title(story['title'])
    for prior in previous:
        prior_key = compact_key(prior.get('key', ''))
        prior_title = normalize_title(prior.get('title', ''))
        same_event = key == prior_key or (title and prior_title and SequenceMatcher(None, title, prior_title).ratio() >= .78)
        if same_event and not meaningful_update(story):
            return True
    return False


def load_history() -> list[dict]:
    if not HISTORY.exists():
        return []
    raw = json.loads(HISTORY.read_text(encoding='utf-8'))
    return raw if isinstance(raw, list) else []


def source(story: dict) -> str:
    source_name = safe(story.get('source', 'Source'))
    published = safe(story.get('published', ''))
    link = url_link(story.get('url', ''), 'Read original reporting')
    return f'<div class="source">{source_name}{f" · {published}" if published else ""} · {link}</div>'


def story_body(story: dict, is_lead: bool = False) -> str:
    html = []
    for paragraph in story.get('paragraphs', []):
        if paragraph.strip():
            html.append(f'<p>{safe(paragraph)}</p>')
    if story.get('why', '').strip():
        html.append(f'<div class="why"><strong>Why it matters:</strong> {safe(story["why"])}</div>')
    return '<div class="article-body">' + ''.join(html) + '</div>' + source(story)


def render(issue: dict, archive: list[str], depth: int = 0, sample: bool = False) -> str:
    prefix = '../' * depth
    date = issue['date']
    date_label = datetime.fromisoformat(date).strftime('%A, %B %-d, %Y')
    lead = issue['lead']
    sections = issue['sections']
    links = ''.join(
        f'<li><a href="#section-{i}"><span>Section {i+1:02d}</span>{safe(section["name"])}</a></li>'
        for i, section in enumerate(sections)
    )
    lead_html = (
        '<section class="lead" aria-label="Front page">'
        '<article>'
        f'<span class="section-kicker">{safe(lead["category"])}</span>'
        f'<h2>{safe(lead["title"])}</h2>'
        f'<p class="deck">{safe(lead["deck"])}</p>'
        f'{story_body(lead, is_lead=True)}'
        '</article>'
        '<aside class="lead-aside"><h3>Inside this edition</h3>'
        f'<ul class="toc">{links}</ul>'
        '<p class="source">Fresh reporting, local perspective, and something unexpected.</p>'
        '</aside>'
        '</section>'
    )
    section_html = []
    for i, section in enumerate(sections):
        stories = []
        for story in section.get('stories', []):
            label = '<span class="update">Update</span> ' if meaningful_update(story) else ''
            stories.append(
                '<article class="story">'
                f'<div class="section-kicker">{safe(story["category"])}</div>'
                f'<h3>{label}{safe(story["title"])}</h3>'
                f'{"<p class=\"deck\">" + safe(story["deck"]) + "</p>" if story.get("deck", "").strip() else ""}'
                f'{story_body(story)}'
                '</article>'
            )
        section_html.append(
            f'<section id="section-{i}"><div class="section-heading"><h2>{safe(section["name"])}</h2></div>'
            f'<div class="stories">{"".join(stories)}</div></section>'
        )
    reads = []
    for read in issue.get('long_reads', []):
        link = url_link(read.get('url', ''), 'Read the feature')
        reads.append(
            '<article class="read">'
            f'<div class="section-kicker">{safe(read["source"])}</div>'
            f'<h3>{safe(read["title"])}</h3>'
            f'<p>{safe(read["description"])}</p>'
            f'<p class="source">{link}</p>'
            '</article>'
        )
    archive_href = prefix + 'archive.html'
    styles_href = prefix + 'styles.css'
    sample_banner = '<div class="banner"><strong>Layout preview.</strong> These are placeholders, not today\'s news. Add your API key and run the publishing workflow for a real edition.</div>' if sample else ''
    return f'''<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#faf8f1"><meta name="description" content="The Morning Edition — a personal newspaper for curious readers.">
<title>The Morning Edition — {safe(date_label)}</title>
<link rel="stylesheet" href="{safe(styles_href)}"><link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>📰</text></svg>">
</head><body>
<div class="shell">
<header><div class="mini-header"><span>Medford · South Jersey · Beyond</span><a href="{safe(archive_href)}">Past editions</a></div>
<div class="masthead"><div class="eyebrow">Independent curiosity · Since 2026</div><h1>The Morning Edition</h1><p>A newspaper for the curious mind</p></div>
<div class="index-line"><span>{safe(date_label)}</span><span>The daily paper · Around 15–20 minutes</span></div></header>
{sample_banner}
<main>{lead_html}{''.join(section_html)}<section><div class="section-heading"><h2>The Reading Room</h2><small>Worth a little more time</small></div><div class="reads">{''.join(reads)}</div></section></main>
<footer><div class="name">The Morning Edition</div><p>Made for reading, not scrolling.</p><p><a href="{safe(archive_href)}">Browse previous editions</a> · News summaries link to original sources.</p></footer>
</div></body></html>'''


def render_archive(dates: list[str]) -> str:
    entries = []
    for d in dates:
        try:
            label = datetime.fromisoformat(d).strftime('%A, %B %-d, %Y')
        except ValueError:
            continue
        entries.append(f'<li><a href="editions/{safe(d)}/">{safe(label)}</a><small>Daily edition</small></li>')
    if not entries:
        entries.append('<li>Published editions will appear here after the first daily run.</li>')
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Archive · The Morning Edition</title><link rel="stylesheet" href="styles.css"></head>
<body><div class="shell"><header><div class="mini-header"><span>South Jersey & Beyond</span><a href="index.html">Today's edition</a></div><div class="masthead"><div class="eyebrow">Your personal newspaper</div><h1>The Morning Edition</h1><p>The archive</p></div></header>
<main><div class="section-heading"><h2>Past Editions</h2></div><ul class="archive-list">{''.join(entries)}</ul></main><footer><div class="name">The Morning Edition</div><p><a href="index.html">Back to the front page</a></p></footer></div></body></html>'''


def all_stories(issue: dict) -> list[dict]:
    return [issue['lead']] + [s for section in issue['sections'] for s in section['stories']]


def prepare_for_publication(issue: dict, history: list[dict]) -> dict:
    """Discard individual bad citations/duplicates before final strict validation.

    Never publish a story without an acceptable direct source URL. When only
    isolated stories fail, keep the rest without an additional paid API request.
    """
    if issue.get('date') != DATE:
        raise ValueError(f'Expected local publication date {DATE}; got {issue.get("date")!r}')

    candidates = [('lead', -1, issue['lead'])]
    for section_index, section in enumerate(issue['sections']):
        candidates.extend(('section', section_index, story) for story in section['stories'])

    accepted = []
    for origin, section_index, story in candidates:
        title = str(story.get('title', '(untitled)')).replace('\n', ' ')[:150]
        reason = None
        if not valid_url(story.get('url', '')):
            reason = 'missing or invalid HTTPS article URL'
        elif not isinstance(story.get('paragraphs'), list) or not any(
            isinstance(p, str) and p.strip() for p in story['paragraphs']
        ):
            reason = 'missing article text'
        elif too_similar(story, history):
            reason = 'already covered without a substantive update'
        elif too_similar({**story, 'update_note': '', 'new_development': ''},
                         [item[2] for item in accepted]):
            reason = 'duplicate within this edition'

        if reason:
            print(f'::warning::Skipped story ({reason}): {title}', flush=True)
        else:
            accepted.append((origin, section_index, story))

    if len(accepted) < 10:
        raise ValueError(
            f'Only {len(accepted)} publishable stories remain after citation/duplicate checks; '
            'keeping the existing edition instead.'
        )

    # If the lead was unpublishable, promote the first remaining story.
    new_lead = accepted[0][2]
    if new_lead is not issue['lead']:
        print(f'::warning::Original lead was rejected; promoted: {new_lead["title"]}', flush=True)

    accepted_ids = {id(item[2]) for item in accepted}
    new_sections = []
    for section in issue['sections']:
        remaining = [s for s in section['stories'] if id(s) in accepted_ids and s is not new_lead]
        if remaining:
            new_sections.append({**section, 'stories': remaining})

    # Apply the same checks to optional reading-room links.
    reads = []
    seen_read_titles = set()
    prior_titles = {normalize_title(item.get('title', '')) for item in history}
    story_titles = {normalize_title(item[2].get('title', '')) for item in accepted}
    for read in issue.get('long_reads', []):
        title = normalize_title(read.get('title', ''))
        if not valid_url(read.get('url', '')):
            print(f'::warning::Skipped reading-room link (invalid URL): {read.get("title", "")}', flush=True)
        elif title in prior_titles or title in story_titles or title in seen_read_titles:
            print(f'::warning::Skipped repeated reading-room item: {read.get("title", "")}', flush=True)
        else:
            reads.append(read)
            seen_read_titles.add(title)

    discarded = len(candidates) - len(accepted)
    if discarded:
        print(f'Quality check kept {len(accepted)} stories and skipped {discarded}; no new API call required.', flush=True)
    return {**issue, 'lead': new_lead, 'sections': new_sections, 'long_reads': reads}


def validate(issue: dict, history: list[dict]):
    if issue.get('date') != DATE:
        raise ValueError(f'Expected local publication date {DATE}; got {issue.get("date")!r}')
    stories = all_stories(issue)
    if len(stories) < 10:
        raise ValueError(f'Only {len(stories)} stories, too few for a complete issue; previous issue remains live.')
    if not valid_url(issue['lead']['url']):
        raise ValueError('Lead article is missing a secure source URL')
    seen = []
    for story in stories:
        if not isinstance(story.get('paragraphs'), list) or not story['paragraphs']:
            raise ValueError(f'Missing text in: {story.get("title")}')
        if not valid_url(story.get('url', '')):
            raise ValueError(f'Invalid source URL in: {story.get("title")}')
        if too_similar(story, history):
            raise ValueError(f'Repeated old story without meaningful update: {story.get("title")}')
        if too_similar({**story, 'update_note': '', 'new_development': ''}, seen):
            raise ValueError(f'Repeated story within the same issue: {story.get("title")}')
        seen.append(story)
    for read in issue.get('long_reads', []):
        if not valid_url(read.get('url', '')):
            raise ValueError('Long read missing valid source URL')
        if any(normalize_title(read.get('title', '')) == normalize_title(h.get('title', '')) for h in history):
            raise ValueError(f'Recycled reading-room selection: {read.get("title")}')


def generate(history: list[dict]) -> dict:
    from openai import OpenAI

    # Retain a bounded history to control prompt costs, giving recent days priority.
    recent = history[-160:]
    prompt = f'''Today in America/New_York is {DATE}. Prepare one complete newspaper edition.

{EDITORIAL.read_text(encoding="utf-8")}

PREVIOUSLY PUBLISHED STORY LOG (do NOT recycle these unless substantial new developments):
{json.dumps(recent, ensure_ascii=False)}

RESEARCH REQUIREMENTS:
- USE web search for fresh reporting and source links. Research several varied categories, including local South Jersey/Philadelphia and recent sports results.
- Real events ONLY. Do not invent scores, publication dates, quotes, places, article URLs, or source names. If an item cannot be verified with search evidence, omit it.
- Direct https URL to the actual source article (NOT google.com search URLs, not fake links).
- Ensure the lead and main stories are current; older science/history features must clearly convey their age.
- Select roughly 18–24 DIFFERENT news stories across about five sections, plus 2–3 optional longer reads. Aim for several paragraphs in each major story and compact briefs for the rest.
- A story already in the previous issue is NOT fresh just because another publisher wrote it. Include only if a consequential development occurred since last appearance; mark update_note='UPDATE', write new_development explicitly and lead with that NEW fact. Otherwise never repeat.
- Be mindful of the reader's local teams, not just national sports generalities. Include scores only when actually verified.
- Provide source URL, source name and published date when confirmed. Never use a placeholder, homepage, bare domain, citation token, Markdown link, or fabricated URL. If there is no verified direct HTTPS article URL, omit the story entirely.
- Do not use markdown formatting inside JSON text fields. Make accurate, original summaries, not copied paragraphs.
- Output a VALID JSON object matching the requested schema; date must be {DATE}.
'''
    client = OpenAI()
    response = client.responses.create(
        model=MODEL,
        tools=[{'type': 'web_search'}],
        tool_choice='required',
        input=[
            {'role': 'system', 'content': 'You are the careful editor of a trusted local-aware daily newspaper. Verify reporting via web search, prioritize genuine novelty, and output JSON only.'},
            {'role': 'user', 'content': prompt},
        ],
        text={'format': {'type': 'json_schema', 'name': 'morning_edition', 'strict': True, 'schema': SCHEMA}},
    )
    if not response.output_text:
        raise RuntimeError('API returned no edition text; keeping previous issue unchanged')
    return json.loads(response.output_text)


def publish(issue: dict, history: list[dict]):
    folder = SITE / 'editions' / DATE
    folder.mkdir(parents=True, exist_ok=True)
    dates = sorted([p.name for p in (SITE / 'editions').iterdir() if p.is_dir() and re.fullmatch(r'\d{4}-\d{2}-\d{2}', p.name)] + [DATE], reverse=True)
    dates = list(dict.fromkeys(dates))
    html = render(issue, dates)
    # Validate and render first. Writes follow only when all have succeeded.
    updates = []
    for story in all_stories(issue):
        updates.append({'date': DATE, 'key': compact_key(story['key']), 'title': story['title']})
    for read in issue.get('long_reads', []):
        updates.append({'date': DATE, 'key': compact_key('longread-' + read['title']), 'title': read['title']})
    new_history = [h for h in history if h.get('date') != DATE] + updates
    new_history = new_history[-2000:]
    (folder / 'index.html').write_text(render(issue, dates, depth=2), encoding='utf-8')
    (folder / 'edition.json').write_text(json.dumps(issue, indent=2, ensure_ascii=False), encoding='utf-8')
    (SITE / 'index.html').write_text(html, encoding='utf-8')
    (SITE / 'archive.html').write_text(render_archive(dates), encoding='utf-8')
    HISTORY.write_text(json.dumps(new_history, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'Published {DATE} with {len(all_stories(issue))} stories and {len(issue.get("long_reads", []))} long reads')


def main():
    folder = SITE / 'editions' / DATE
    if folder.exists() and not os.environ.get('FORCE_REGENERATE'):
        print(f'{DATE} has already been published; skipping to avoid duplicate API charges.')
        return
    if not os.environ.get('OPENAI_API_KEY'):
        sys.exit('OPENAI_API_KEY is missing. Set it as a GitHub Actions repository secret; no files were changed.')
    history = load_history()
    issue = generate(history)
    issue = prepare_for_publication(issue, history)
    validate(issue, history)
    publish(issue, history)


if __name__ == '__main__':
    main()
