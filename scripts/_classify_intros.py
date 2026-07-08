import re, os
picks = [l.split('=')[-1].strip() for l in open('research/video_library/day_intra/_picks.txt')]
for vid in picks:
    f = f'research/video_library/day_intra/{vid}/transcript.md'
    if not os.path.exists(f):
        print(f'--- {vid} --- (no transcript)\n'); continue
    txt = open(f, encoding='utf-8', errors='ignore').read()
    lines = [re.sub(r'^\[.*?\]\s*', '', l).strip() for l in txt.splitlines() if l.startswith('[')]
    body = ' '.join(lines)[:300]
    print(f'--- {vid} ---'); print(body); print()
