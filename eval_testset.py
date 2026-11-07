"""Measure detection quality on the held-out annotated set (testset_claims_v1.py).

    python eval_testset.py            # summary
    python eval_testset.py --misses   # also list every miss and false alarm
    python eval_testset.py --v2       # the social-detection set (testset_claims_v2.py)

Recall = flagged sentences that were reported; false alarms = no_flag sentences that were reported; category agreement = a reported sentence got
a type that matches one of the acceptable categories. Detection is judged per sentence, inside the whole paragraph (so neighbouring claims
interact exactly as they do on a real page).
"""
import re
import sys
import app
import importlib
ts = importlib.import_module('testset_claims_v2' if '--v2' in sys.argv else 'testset_claims_v1')

TYPE_TO_CAT = [
    ('forced-labour', 'forced'), ('supply-chain', 'supplier'), ('supplier', 'supplier'), ('human-rights or labour', 'humanrights'),
    ('human-rights / labour', 'humanrights'), ('health', 'safety'), ('diversity', 'diversity'), ('social-impact', 'community'),
    ('aspirational', 'aspirational'), ('climate-neutrality', 'neutral'), ('future environmental', 'future'), ('recycled', 'recycl'),
    ('absolute', 'absolute'), ('comparative', 'comparative'), ('label', 'label'), ('visual', 'label'), ('generic', 'generic'),
    ('legal requirement', 'generic'),
]


def cat_of(type_name):
    low = type_name.lower()
    for key, cat in TYPE_TO_CAT:
        if key in low:
            return cat
    return low


def norm(text):
    return re.sub(r'\W+', ' ', str(text or '').lower().replace(' ', ' ')).strip()


def findings_for(paragraph):
    """(dimension, category, matched phrase) per finding. A finding is tied to a sentence by the phrase that triggered it, not by the text it
    quotes: the quoted passage may carry a neighbouring sentence as context."""
    out = []
    for dim, fn in (('green', app.detect_green_claims), ('social', app.detect_claims)):
        for f in fn(paragraph):
            if not app.is_placeholder_finding(f['type']):
                out.append((dim, cat_of(f['type']), norm(f.get('matched_phrase') or ''), norm(f.get('full_claim_text') or f.get('claim'))))
    return out


def belongs_to(claim_text, sentence_key):
    """A finding belongs to a sentence when its matched phrase is in the sentence AND the passage it quotes is that sentence (or a passage
    around it). Without the second test a correct finding on "Our cocoa comes from farms that do not use child labour." would count as a
    false alarm on a neighbouring "Child labour is a known risk" that only shares the phrase."""
    if not claim_text:
        return True
    return sentence_key in claim_text or claim_text in sentence_key


def run(module=None):
    stats = {}
    detail = []
    for item_id, lang, sentences in (module or ts).ITEMS:
        paragraph = ' '.join(s[0] for s in sentences)
        found = findings_for(paragraph)
        for sentence, label, dim, cats in sentences:
            if label == 'ctx':
                continue
            key = norm(sentence)
            hits = [f for f in found if f[2] and re.search(r'(?<!\w)' + re.escape(f[2]) + r'(?!\w)', key) and belongs_to(f[3], key)]
            bucket = stats.setdefault((lang, label), {'n': 0, 'ok': 0, 'cat_ok': 0})
            bucket['n'] += 1
            if label == 'flag':
                if hits:
                    bucket['ok'] += 1
                    if any(h[1] in cats for h in hits):
                        bucket['cat_ok'] += 1
                    else:
                        detail.append(('WRONG TYPE', item_id, sentence, sorted({h[1] for h in hits}), cats))
                else:
                    detail.append(('MISS', item_id, sentence, [], cats))
            else:
                if not hits:
                    bucket['ok'] += 1
                else:
                    detail.append(('FALSE ALARM', item_id, sentence, sorted({h[1] for h in hits}), []))
    return stats, detail


def summarise(stats):
    rows = []
    totals = {'flag': [0, 0, 0], 'no_flag': [0, 0, 0]}
    for lang in ('en', 'nl', 'fr'):
        fl = stats.get((lang, 'flag'), {'n': 0, 'ok': 0, 'cat_ok': 0})
        nf = stats.get((lang, 'no_flag'), {'n': 0, 'ok': 0, 'cat_ok': 0})
        rows.append((lang, fl, nf))
        for k, b in (('flag', fl), ('no_flag', nf)):
            totals[k][0] += b['n']; totals[k][1] += b['ok']; totals[k][2] += b['cat_ok']
    return rows, totals


def pct(a, b):
    return 'n/a' if not b else f'{100 * a / b:.0f}%'


if __name__ == '__main__':
    stats, detail = run()
    rows, totals = summarise(stats)
    print('Language | recall (flag) | right type | correctly left alone (no_flag)')
    for lang, fl, nf in rows:
        print(f"{lang:8} | {fl['ok']}/{fl['n']} = {pct(fl['ok'], fl['n']):>4} | {fl['cat_ok']}/{fl['n']} = {pct(fl['cat_ok'], fl['n']):>4} | {nf['ok']}/{nf['n']} = {pct(nf['ok'], nf['n'])}")
    f, n = totals['flag'], totals['no_flag']
    print(f"{'total':8} | {f[1]}/{f[0]} = {pct(f[1], f[0]):>4} | {f[2]}/{f[0]} = {pct(f[2], f[0]):>4} | {n[1]}/{n[0]} = {pct(n[1], n[0])}")
    if '--misses' in sys.argv:
        print()
        for kind, item_id, sentence, got, cats in detail:
            print(f'{kind:12} {item_id}  {sentence[:90]}  got={got} expected={cats}')
