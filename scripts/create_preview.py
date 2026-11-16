"""Only creates an explicitly labeled SAMPLE page. It does not use an API key."""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from build import render, render_archive, SITE

date=datetime.now(ZoneInfo('America/New_York')).strftime('%Y-%m-%d')
def article(title,cat,deck,paras):
    return {'key':title.lower().replace(' ','-'), 'category':cat, 'title':title,'deck':deck,
            'paragraphs':paras,'why':'','source':'Layout example (not a news source)','url':'',
            'published':'','update_note':'','new_development':''}
issue={'date':date,
  'lead': article('Your own newspaper, delivered every morning','A NOTE FROM THE EDITOR',
           'A quiet place to catch up on the world, your community, and the things you never knew you wanted to learn.',
           ['This is a sample page to show the design. No real news has been generated yet. Once you add your OpenAI API key and run the workflow, this space becomes the daily lead story.',
            'The finished paper will include important reporting from the United States and abroad, meaningful local news from Medford and Philadelphia, regular sports coverage, developments in science and technology, and occasional unexpected discoveries.',
            'Each headline will point to original reporting, and a simple story-history record will help the next edition avoid repeating yesterday’s news.']),
  'sections':[
    {'name':'The World & Washington','stories':[
        article('Reporting that explains why the day matters','NATIONAL & WORLD','', ['Major events will receive context, not just a headline. The newspaper will aim to explain what happened, what remains uncertain, and why it matters.']),
        article('Politics and the economy in proportion','PUBLIC POLICY','',['The biggest political and economic stories will appear here without overwhelming the other parts of the paper.'])]},
    {'name':'Close to Home','stories':[
        article('Medford, Burlington County and the region','COMMUNITY','',['Civic decisions, school matters, infrastructure, new businesses and community events will make this section genuinely useful locally.']),
        article('Philadelphia and South Jersey','REGIONAL NEWS','',['Regional developments will receive attention when they affect daily life or offer an interesting story.'])]},
    {'name':'Science, Engineering & Discovery','stories':[
        article('Ideas worth understanding','RESEARCH','',['From new findings in astronomy to practical breakthroughs in energy and engineering, this section is for curiosity beyond a scrolling news feed.']),
        article('An unexpected discovery','THE CURIOSITY PAGE','',['Each issue will leave room for a surprising story that was worth finding, even if it does not match any particular hobby.'])]},
    {'name':'Technology, Culture & Sports','stories':[
        article('Industry-shaping technology and entertainment','TECHNOLOGY & CULTURE','',['Coverage will focus on meaningful announcements, important research, new products and major gaming releases—not routine patch notes.']),
        article('The Philadelphia sports desk','NFL · MLB · NBA · NHL','',['Eagles, Phillies, 76ers and Flyers coverage, plus meaningful national sports storylines and verified results.'])]},
  ],
  'long_reads':[
    {'title':'A good investigation','description':'A substantial story from a credible newsroom that rewards a longer read.','source':'Coming soon','url':''},
    {'title':'A scientific mystery','description':'Interesting research, explained without hype.','source':'Coming soon','url':''},
    {'title':'Something entirely unexpected','description':'The kind of article you discover by turning a newspaper page.','source':'Coming soon','url':''},
  ]}
(SITE/'index.html').write_text(render(issue, [], sample=True),encoding='utf-8')
(SITE/'archive.html').write_text(render_archive([]),encoding='utf-8')
print('Created labeled demo front page.')
