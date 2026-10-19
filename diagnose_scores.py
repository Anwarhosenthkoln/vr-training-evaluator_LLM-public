import os, json

reports_dir = 'data/reports'
files = sorted(f for f in os.listdir(reports_dir) if f.endswith('_report.json'))
for rf in files:
    with open(os.path.join(reports_dir, rf), encoding='utf-8') as fh:
        r = json.load(fh)
    name = rf.replace('_report.json','')
    bd = r['score_breakdown']
    score = r['overall_score']
    verdict = r['verdict']
    c = bd['completeness']['points_deducted']
    t = bd['timing']['points_deducted']
    o = bd['order']['points_deducted']
    cr = bd['critical_errors']['points_deducted']
    print(f'{name}: {score} ({verdict})')
    print(f'  completeness=-{c}  timing=-{t}  order=-{o}  critical=-{cr}')
    for fb in r.get('feedback', []):
        if 'late' in fb.lower() or 'Late' in fb or 'Physician' in fb or 'contact' in fb.lower():
            print(f'  >> {fb}')
    print()
