"""Versioned, explicit name expansion; related fields remain separate matches."""
import difflib
import json
import unicodedata
from functools import lru_cache
from config import BASE_DIR


def normalize(value):
    return ''.join(unicodedata.normalize('NFKC', str(value or '')).casefold().split()).replace('台', '臺').replace('巿', '市')


@lru_cache(maxsize=1)
def rules():
    return json.loads((BASE_DIR / 'data/processed/campus_search_rules.json').read_text(encoding='utf-8'))


def expand(query):
    keyword = normalize(query)
    direct = (keyword,) if keyword else ()
    families, alias = [], False
    for family in rules()['families']:
        for short, terms in family['aliases'].items():
            if keyword in {normalize(short + suffix) for suffix in ('', '系', '學系')}:
                direct = tuple(normalize(term) for term in terms)
                alias = True
        if keyword and (any(keyword == normalize(term) or keyword in normalize(term) or normalize(term) in keyword for term in family['terms'])
                        or any(keyword in {normalize(short + suffix) for suffix in ('', '系', '學系')} for short in family['aliases'])):
            families.append(family)
    related = tuple(dict.fromkeys(normalize(term) for family in families for term in family['terms']
                                  if not any(normalize(term) == term2 for term2 in direct)))
    return {'keyword': keyword, 'direct': direct, 'related': related, 'alias': alias,
            'version': rules()['version'], 'families': [family['label'] for family in families]}


def suggestions(query, department_names):
    # Suggest actual names only; never silently rewrite or change the radius.
    if len(normalize(query)) < 3:
        return []
    names = {normalize(name): name for name in department_names}
    for family in rules()['families']:
        for term in family['terms']:
            if any(normalize(term) in name for name in names):
                names[normalize(term)] = term
    hits = difflib.get_close_matches(normalize(query), sorted(names), n=3, cutoff=.65)
    return [names[key] for key in hits if key != normalize(query)]
