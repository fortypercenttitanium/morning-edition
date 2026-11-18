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
        'source': {'type': 'string'},
        'url': {'type': 'string'},
        'published': {'type': 'string', 'description': 'Source article publication date YYYY-MM-DD when verified; otherwise empty string'},
        'update_note': {'type': 'string', 'description': 'UPDATE only if substantial new fact since last issue; otherwise empty string'},
        'new_development': {'type': 'string', 'description': 'Explain the specific new development since prior report for UPDATE; otherwise empty string'},
    },
    'required': ['key', 'category', 'title', 'deck', 'paragraphs', 'source', 'url', 'published', 'update_note', 'new_development'],
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



# A second, lower-cost copy-editor pass rewrites the issue from the already
# researched material. It cannot introduce new URLs or source articles:
# source_keys are resolved against the original issue in Python.
EDIT_STORY_SCHEMA = {
    'type': 'object',
    'properties': {
        'source_keys': {'type': 'array', 'items': {'type': 'string'}},
        'title': {'type': 'string'},
        'deck': {'type': 'string'},
        'paragraphs': {'type': 'array', 'items': {'type': 'string'}},
    },
    'required': ['source_keys', 'title', 'deck', 'paragraphs'],
    'additionalProperties': False,
}
EDIT_SCHEMA = {
    'type': 'object',
    'properties': {
        'lead': EDIT_STORY_SCHEMA,
        'sections': {'type': 'array', 'items': {
            'type': 'object',
            'properties': {
                'name': {'type': 'string'},
                'stories': {'type': 'array', 'items': EDIT_STORY_SCHEMA},
            },
            'required': ['name', 'stories'],
            'additionalProperties': False,
        }},
        'long_read_indices': {'type': 'array', 'items': {'type': 'integer'}},
    },
    'required': ['lead', 'sections', 'long_read_indices'],
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



def canonical_source_url(url: str) -> str:
    """Normalize URLs enough to identify the same linked article twice."""
    if not valid_url(url):
        return ''
    parsed = urlparse(url)
    path = parsed.path.rstrip('/') or '/'
    # Article paths identify a story; ignore campaign/tracking query strings.
    query = parsed.query if path == '/' else ''
    return f'{parsed.netloc.lower()}{path}?{query}'


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
        prior_keys = {compact_key(prior.get('key', ''))}
        prior_keys.update(compact_key(k) for k in prior.get('merged_keys', []))
        prior_title = normalize_title(prior.get('title', ''))
        same_event = key in prior_keys or (title and prior_title and SequenceMatcher(None, title, prior_title).ratio() >= .78)
        if same_event and not meaningful_update(story):
            return True
    return False


def load_history() -> list[dict]:
    if not HISTORY.exists():
        return []
    raw = json.loads(HISTORY.read_text(encoding='utf-8'))
    return raw if isinstance(raw, list) else []


def source(story: dict) -> str:
    links = []
    urls_seen = set()
    for item in [story] + story.get('additional_sources', []):
        url = item.get('url', '')
        canonical = canonical_source_url(url)
        if not canonical or canonical in urls_seen:
            continue
        urls_seen.add(canonical)
        name = str(item.get('source') or 'Original reporting')
        date = str(item.get('published') or '')
        label = name + (f' · {date}' if date else '')
        links.append(url_link(url, label))
    return '<div class="source">Sources: ' + ' · '.join(links) + '</div>'


def story_body(story: dict, is_lead: bool = False) -> str:
    html = []
    for paragraph in story.get('paragraphs', []):
        if paragraph.strip():
            html.append(f'<p>{safe(paragraph)}</p>')
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


def apply_copy_edit(issue: dict, edited: dict) -> dict:
    """Rebuild a consolidated issue from a copy editor's source-key references.

    Source URLs and dates are always inherited from the researched draft, never
    from the copy editor's output. Each original article can be used only once.
    """
    originals = {}
    for story in all_stories(issue):
        key = story['key']
        if key in originals:
            raise ValueError(f'Original issue reused story key {key!r}')
        originals[key] = story

    used = set()

    def rebuild(draft: dict) -> dict:
        keys = draft.get('source_keys', [])
        if not isinstance(keys, list) or not keys or len(set(keys)) != len(keys):
            raise ValueError('Copy editor returned invalid source_keys')
        if any(key not in originals or key in used for key in keys):
            raise ValueError('Copy editor invented or reused an original story key')
        paragraphs = draft.get('paragraphs', [])
        if not isinstance(paragraphs, list) or not any(
            isinstance(p, str) and p.strip() for p in paragraphs
        ):
            raise ValueError('Copy editor returned an empty article')
        if not isinstance(draft.get('title'), str) or not draft['title'].strip():
            raise ValueError('Copy editor returned a missing headline')
        used.update(keys)

        originals_for_story = [originals[key] for key in keys]
        # An invalid first source should not invalidate a merged article that
        # contains other usable source citations.
        primary = next(
            (s for s in originals_for_story if valid_url(s.get('url', ''))),
            originals_for_story[0],
        )
        additional = []
        seen_urls = {canonical_source_url(primary.get('url', ''))}
        for item in originals_for_story:
            url = item.get('url', '')
            canonical = canonical_source_url(url)
            if canonical and canonical not in seen_urls:
                additional.append({
                    'source': item.get('source', 'Original reporting'),
                    'url': url,
                    'published': item.get('published', ''),
                })
                seen_urls.add(canonical)

        return {
            **primary,
            'title': draft['title'].strip(),
            'deck': str(draft.get('deck') or '').strip(),
            'paragraphs': [p.strip() for p in paragraphs if isinstance(p, str) and p.strip()],
            'merged_keys': keys,
            'additional_sources': additional,
        }

    lead = rebuild(edited['lead'])
    sections = []
    for section in edited['sections']:
        stories = [rebuild(story) for story in section['stories']]
        if stories:
            sections.append({'name': section['name'], 'stories': stories})

    reads = []
    used_reads = set()
    for index in edited['long_read_indices']:
        if not isinstance(index, int) or index < 0 or index >= len(issue['long_reads']) or index in used_reads:
            raise ValueError('Copy editor returned an invalid or reused long-read index')
        reads.append(issue['long_reads'][index])
        used_reads.add(index)

    print(
        f'Copy desk combined {len(originals)} article drafts into '
        f'{1 + sum(len(s["stories"]) for s in sections)} distinct stories.',
        flush=True,
    )
    return {**issue, 'lead': lead, 'sections': sections, 'long_reads': reads}


def copy_edit(issue: dict) -> dict:
    """Use a cheaper model, without web search, to merge overlapping coverage.

    A separate pass catches topic duplicates that unrelated headlines, different
    outlet URLs and model-generated story IDs cannot detect reliably.
    """
    from openai import OpenAI

    candidates = [
        {
            'key': s['key'], 'category': s.get('category', ''),
            'title': s['title'], 'deck': s.get('deck', ''),
            'paragraphs': s.get('paragraphs', []), 'source': s.get('source', ''),
            'url': s.get('url', ''),
        }
        for s in all_stories(issue)
    ]
    payload = {
        'articles': candidates,
        'reading_room': [
            {'index': i, 'title': r['title'], 'description': r.get('description', ''), 'url': r.get('url', '')}
            for i, r in enumerate(issue.get('long_reads', []))
        ],
    }
    prompt = (
        'Edit this already-researched newspaper. The article drafts come from verified source searches; '
        'do NOT add facts, quotes, dates, events, URLs, or sources. Output only the supplied schema.\n'
        'CRITICAL: One story per underlying news event, summit, announcement or development, '
        'REGARDLESS of how many publishers, headlines, categories, angles or source URLs cover it. '
        'For instance, five stories about a Trump-Xi meeting, its trade negotiations and related '
        'diplomacy should normally become ONE substantive, well-written article, not five briefs. '
        'Combine nonredundant facts into a coherent article with several short paragraphs, and '
        'list every contributing original article key in source_keys. Grouped stories will automatically '
        'retain multiple source links. A truly independent event may remain separate.\n'
        'Copy-edit ALL articles for a neutral, informative newspaper voice. NEVER explain why the '
        'story was selected for this newspaper, why readers should care, or whether it is inspiring '
        'or interesting. Remove formulaic lines like "Why it matters", "a reminder that", '
        '"it is a fitting story", "for South Jersey readers", "the kind of story worth reading", '
        'or self-referential observations about journalism. Give the relevant facts and context '
        'directly without pleading for interest or talking to the reader. Keep straightforward '
        'implications only when supported by the researched text. Avoid vague speculative conclusions.\n'
        'Use each original key at most once; use only keys present in the supplied input, and '
        'retain distinct important stories. Keep one lead and sensible sections. The exact story '
        'count is NOT a quota, and fewer good articles beat repeated coverage. Return reading_room '
        'indices only for features that do not restate subjects covered by an included article. '
        'Do not add new reading-room entries.\n\n'
        + json.dumps(payload, ensure_ascii=False)
    )
    response = OpenAI().responses.create(
        model=os.environ.get('OPENAI_COPY_EDITOR_MODEL', 'gpt-5.4-mini'),
        input=[
            {'role': 'system', 'content': 'You are a rigorous newspaper copy editor. Merge coverage of the same underlying event, retain factual attribution, and remove editorial self-justification.'},
            {'role': 'user', 'content': prompt},
        ],
        text={'format': {'type': 'json_schema', 'name': 'morning_edition_copy_edit', 'strict': True, 'schema': EDIT_SCHEMA}},
    )
    if not response.output_text:
        raise ValueError('Copy editor returned no edited issue')
    return apply_copy_edit(issue, json.loads(response.output_text))


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
        elif any(canonical_source_url(story.get('url', '')) == canonical_source_url(item[2].get('url', '')) for item in accepted):
            reason = 'same source article already covered in this edition'
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
    article_urls = {canonical_source_url(item[2].get('url', '')) for item in accepted}
    for item in accepted:
        article_urls.update(canonical_source_url(extra.get('url', '')) for extra in item[2].get('additional_sources', []))
    for read in issue.get('long_reads', []):
        title = normalize_title(read.get('title', ''))
        if not valid_url(read.get('url', '')):
            print(f'::warning::Skipped reading-room link (invalid URL): {read.get("title", "")}', flush=True)
        elif canonical_source_url(read.get('url', '')) in article_urls or title in prior_titles or title in story_titles or title in seen_read_titles:
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
    seen_urls = set()
    for story in stories:
        if not isinstance(story.get('paragraphs'), list) or not story['paragraphs']:
            raise ValueError(f'Missing text in: {story.get("title")}')
        if not valid_url(story.get('url', '')):
            raise ValueError(f'Invalid source URL in: {story.get("title")}')
        if canonical_source_url(story.get('url', '')) in seen_urls:
            raise ValueError(f'Repeated source article within the issue: {story.get("title")}')
        if too_similar(story, history):
            raise ValueError(f'Repeated old story without meaningful update: {story.get("title")}')
        if too_similar({**story, 'update_note': '', 'new_development': ''}, seen):
            raise ValueError(f'Repeated story within the same issue: {story.get("title")}')
        seen.append(story)
        seen_urls.add(canonical_source_url(story.get('url', '')))
        seen_urls.update(canonical_source_url(s.get('url', '')) for s in story.get('additional_sources', []))
    for read in issue.get('long_reads', []):
        if not valid_url(read.get('url', '')):
            raise ValueError('Long read missing valid source URL')
        if canonical_source_url(read.get('url', '')) in seen_urls:
            raise ValueError(f'Recycled reading-room article: {read.get("title")}')
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
- Select roughly 18–24 DISTINCT underlying news events (not article links) across about five sections, plus 2–3 optional longer reads. One summit, meeting, controversy, announcement, or event gets ONE cohesive article even if many sources cover it. Do not parcel out different angles of the same story to hit a quota. Aim for several paragraphs in each major story and compact briefs for the rest.
- A story already in the previous issue is NOT fresh just because another publisher wrote it. Include only if a consequential development occurred since last appearance; mark update_note='UPDATE', write new_development explicitly and lead with that NEW fact. Otherwise never repeat.
- Be mindful of the reader's local teams, not just national sports generalities. Include scores only when actually verified.
- Provide source URL, source name and published date when confirmed. Never use a placeholder, homepage, bare domain, citation token, Markdown link, or fabricated URL. If there is no verified direct HTTPS article URL, omit the story entirely.
- Write like a straightforward newspaper, never discussing why an article belongs in this newspaper, why readers should care, or what is interesting about the coverage. No 'Why it matters' boxes, justification, motivational conclusions, or meta-commentary about journalism. Integrate verified context into factual paragraphs when warranted.
- Do not use markdown formatting inside JSON text fields. Make accurate, original summaries, not copied paragraphs.
- Output a VALID JSON object matching the requested schema; date must be {DATE}.
'''
    client = OpenAI()
    response = client.responses.create(
        model=MODEL,
        tools=[{'type': 'web_search'}],
        tool_choice='required',
        input=[
            {'role': 'system', 'content': 'You are a rigorous newspaper reporter. Verify reporting via web search, prioritize one article per underlying event, avoid editorial self-justification, and output JSON only.'},
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
        for key in dict.fromkeys(story.get('merged_keys') or [story['key']]):
            updates.append({'date': DATE, 'key': compact_key(key), 'title': story['title']})
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
    try:
        issue = copy_edit(issue)
    except Exception as exc:
        # Publishing should not depend on the optional editorial API call.
        # Local URL/title filters still run, and no extra web research is billed.
        print(f'::warning::Copy-editor pass failed ({type(exc).__name__}: {exc}); using source-checked draft.', flush=True)
    issue = prepare_for_publication(issue, history)
    validate(issue, history)
    publish(issue, history)


if __name__ == '__main__':
    main()
