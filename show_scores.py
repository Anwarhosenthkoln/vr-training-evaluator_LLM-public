import os, json

reports_dir = os.path.abspath('data/reports')
files = sorted(f for f in os.listdir(reports_dir) if f.endswith('_report.json'))
print(f'Total reports: {len(files)}')
print()
for rf in files:
    with open(os.path.join(reports_dir, rf), encoding='utf-8') as fh:
        r = json.load(fh)
    name = rf.replace('_report.json', '')
    score = r['overall_score']
    verdict = r['verdict']
    criticals = r.get('critical_errors', [])
    print(f'{name}')
    print(f'  Score: {score} | Verdict: {verdict}')
    if criticals:
        print(f'  Critical: {criticals}')
    print()
