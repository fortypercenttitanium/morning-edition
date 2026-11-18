"""Offline publication safety tests: never call the paid API."""
import unittest
from scripts import build


TITLES = [
    'City council adopts transit plan',
    'Astronomers discover unusually early quasar',
    'Eagles quarterback returns from injury',
    'NASA prepares new lunar science probe',
    'Lawmakers debate property tax reform',
    'Archaeologists uncover ancient Roman theater',
    'Scientists map recovering coastal mangroves',
    'Manufacturer builds a renewable energy facility',
    'Philadelphia Orchestra begins international tour',
    'Supreme Court weighs new school funding rules',
    'Chipmakers announce a low-power semiconductor process',
    'Regional nonprofit expands food assistance',
]


def story(i, **overrides):
    item = {
        'key': f'event-{i}', 'category': 'News', 'title': TITLES[i],
        'deck': 'A concise summary', 'paragraphs': ['Verified summary text.'],
        'why': '', 'source': 'Example News',
        'url': f'https://news.example.test/articles/{i}', 'published': build.DATE,
        'update_note': '', 'new_development': '',
    }
    item.update(overrides)
    return item


def issue(count=12, **overrides):
    value = {'date': build.DATE, 'lead': story(0), 'sections': [
        {'name': 'News', 'stories': [story(n) for n in range(1, count)]}
    ], 'long_reads': []}
    value.update(overrides)
    return value


class PublicationTests(unittest.TestCase):
    def test_source_url_requires_real_https_article_address(self):
        good = ('https://apnews.com/article/a-story', 'https://whyy.org/articles/a-story/',
                'https://news.site.org/?p=123')
        bad = ('', 'not a URL', 'http://apnews.com/article/a',
               'https://example.com/placeholder', 'https://news.example.test',
               'https://news.example.test/', 'https://news.example.test/path with spaces',
               'https://user:password@news.example.test/article', 'https://[invalid')
        for url in good:
            with self.subTest(url=url):
                self.assertTrue(build.valid_url(url))
        for url in bad:
            with self.subTest(url=url):
                self.assertFalse(build.valid_url(url))

    def test_one_bad_citation_is_removed_and_rest_publishes(self):
        raw = issue()
        raw['sections'][0]['stories'][3]['url'] = 'not a real URL'
        cleaned = build.prepare_for_publication(raw, [])
        self.assertEqual(len(build.all_stories(cleaned)), 11)
        self.assertEqual(len(build.all_stories(raw)), 12)
        build.validate(cleaned, [])

    def test_bad_lead_is_replaced_with_first_eligible_story(self):
        raw = issue()
        raw['lead']['url'] = ''
        cleaned = build.prepare_for_publication(raw, [])
        self.assertEqual(cleaned['lead']['key'], 'event-1')
        self.assertEqual(len(build.all_stories(cleaned)), 11)
        self.assertNotIn('event-1', [s['key'] for sect in cleaned['sections'] for s in sect['stories']])
        build.validate(cleaned, [])

    def test_old_story_without_update_is_removed(self):
        raw = issue()
        history = [{'date': '2026-11-14', 'key': 'event-4', 'title': TITLES[4]}]
        cleaned = build.prepare_for_publication(raw, history)
        self.assertNotIn('event-4', [s['key'] for s in build.all_stories(cleaned)])
        build.validate(cleaned, history)

    def test_same_issue_duplicate_even_if_marked_update(self):
        raw = issue()
        raw['sections'][0]['stories'][4].update({
            'key': 'event-3', 'title': TITLES[3], 'update_note': 'UPDATE',
            'new_development': 'This update contains a substantial difference in the event narrative.'})
        cleaned = build.prepare_for_publication(raw, [])
        self.assertEqual(len(build.all_stories(cleaned)), 11)
        build.validate(cleaned, [])

    def test_unreliable_long_reads_are_dropped(self):
        raw = issue()
        raw['long_reads'] = [
            {'title': 'Working feature', 'description': 'Read more', 'source': 'Magazine', 'url': 'https://example.test/features/one'},
            {'title': 'Invalid feature', 'description': 'Read more', 'source': 'Magazine', 'url': 'https://example.com'},
            {'title': 'Working feature', 'description': 'Read more', 'source': 'Magazine', 'url': 'https://example.test/features/two'},
        ]
        cleaned = build.prepare_for_publication(raw, [])
        self.assertEqual(len(cleaned['long_reads']), 1)
        build.validate(cleaned, [])

    def test_too_few_stories_fails_closed(self):
        raw = issue(count=10)
        raw['sections'][0]['stories'][3]['url'] = ''
        with self.assertRaisesRegex(ValueError, 'Only 9 publishable stories'):
            build.prepare_for_publication(raw, [])

    def test_invalid_date_cannot_publish(self):
        with self.assertRaisesRegex(ValueError, 'Expected local publication date'):
            build.prepare_for_publication(issue(date='1999-01-01'), [])


if __name__ == '__main__':
    unittest.main()



class CopyDeskTests(unittest.TestCase):
    def test_three_differently_titled_summit_stories_merge_with_citations(self):
        raw = issue()
        originals = build.all_stories(raw)
        originals[1].update(title='Trump and Xi discuss a trade framework', source='Reuters',
                            url='https://reuters.com/world/us-china-trade-summit')
        originals[2].update(title='Beijing seeks concessions ahead of leaders meeting', source='AP',
                            url='https://apnews.com/article/summit-diplomacy')
        originals[3].update(title='Technology curbs complicate US China talks', source='BBC',
                            url='https://bbc.com/news/articles/china-chip-talks')
        keys = [s['key'] for s in originals]
        edited = {
            'lead': {'source_keys': [keys[0]], 'title': originals[0]['title'],
                     'deck': '', 'paragraphs': ['Reported facts.']},
            'sections': [{
                'name': 'World',
                'stories': [
                    {'source_keys': keys[1:4], 'title': 'Trump and Xi hold wide-ranging trade talks',
                     'deck': 'Several disputes remain.', 'paragraphs': [
                         'The leaders met to discuss tariffs and technology.',
                         'Negotiators also addressed export restrictions and trade terms.'
                     ]},
                    *[{'source_keys': [k], 'title': originals[i]['title'],
                       'deck': '', 'paragraphs': ['Reported facts.']} for i, k in enumerate(keys) if i >= 4],
                ],
            }],
            'long_read_indices': [],
        }
        result = build.apply_copy_edit(raw, edited)
        self.assertEqual(len(build.all_stories(result)), 10)
        merged = result['sections'][0]['stories'][0]
        self.assertEqual(merged['merged_keys'], keys[1:4])
        self.assertEqual(len(merged['additional_sources']), 2)
        html = build.source(merged)
        self.assertIn('Reuters', html)
        self.assertIn('AP', html)
        self.assertIn('BBC', html)
        build.validate(result, [])

    def test_copy_editor_cannot_invent_or_reuse_original_articles(self):
        raw = issue()
        base = {'source_keys': ['does-not-exist'], 'title': 'Invented headline',
                'deck': '', 'paragraphs': ['Body']}
        with self.assertRaisesRegex(ValueError, 'invented or reused'):
            build.apply_copy_edit(raw, {'lead': base, 'sections': [], 'long_read_indices': []})
        first = {**base, 'source_keys': [raw['lead']['key']]}
        with self.assertRaisesRegex(ValueError, 'invented or reused'):
            build.apply_copy_edit(raw, {'lead': first, 'sections': [
                {'name': 'Repeated', 'stories': [first]}], 'long_read_indices': []})

    def test_same_source_article_with_different_headlines_is_filtered(self):
        raw = issue()
        raw['sections'][0]['stories'][3]['url'] = raw['lead']['url']
        cleaned = build.prepare_for_publication(raw, [])
        self.assertEqual(len(build.all_stories(cleaned)), 11)
        build.validate(cleaned, [])

    def test_long_read_cannot_repeat_a_news_article_via_same_url(self):
        raw = issue()
        raw['long_reads'] = [{
            'title': 'A longer look at city transit funding',
            'description': 'Read more', 'source': 'Example',
            'url': raw['lead']['url'],
        }]
        cleaned = build.prepare_for_publication(raw, [])
        self.assertEqual(cleaned['long_reads'], [])
        build.validate(cleaned, [])

    def test_self_justifying_why_does_not_render(self):
        raw = issue()
        raw['lead']['why'] = 'This is an interesting reminder and deserves your attention.'
        html = build.render(raw, archive=[build.DATE])
        self.assertNotIn('This is an interesting reminder', html)
        self.assertNotIn('Why it matters:', html)

    def test_copy_editor_keeps_only_existing_long_reads(self):
        raw = issue()
        raw['long_reads'] = [{'title': 'A source feature', 'description': 'A long read',
                              'source': 'Source', 'url': 'https://news.example.test/features/123'}]
        first = {'source_keys': [raw['lead']['key']], 'title': raw['lead']['title'],
                 'deck': '', 'paragraphs': ['Article text.']}
        with self.assertRaisesRegex(ValueError, 'invalid or reused long-read'):
            build.apply_copy_edit(raw, {'lead': first, 'sections': [],
                                        'long_read_indices': [0, 0]})
