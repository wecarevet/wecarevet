#!/usr/bin/env python3
"""Injects scripts/mdm/data.json into template.html -> md-meta.html at the repo root.

Run after build_data.py: python3 scripts/mdm/build.py
Also refreshes <workspace>/documents/md-meta.html when this checkout sits inside the
user's workspace (a convenience copy; CI only writes the repo file).
"""
import json, os, datetime, sys

BASE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(BASE, '..', '..'))
WORKSPACE = os.path.abspath(os.path.join(REPO, '..'))
TEMPLATE = os.path.join(BASE, 'template.html')
DATA = os.path.join(BASE, 'data.json')

KST = datetime.timezone(datetime.timedelta(hours=9))

stamp = datetime.datetime.now(KST).strftime('%Y-%m-%dT%H:%M:%S+09:00')
data = json.load(open(DATA, encoding='utf-8'))
data = {**{'builtAt': stamp}, **data}

tpl = open(TEMPLATE, encoding='utf-8').read()
if '__DATA__' not in tpl:
    sys.exit('build: template.html has no __DATA__ placeholder')
js = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
out = tpl.replace('__DATA__', js)

dest = os.path.join(REPO, 'md-meta.html')
with open(dest, 'w', encoding='utf-8') as f:
    f.write(out)
print('wrote', dest, len(out), 'bytes')

docs_dir = os.path.join(WORKSPACE, 'documents')
if os.path.isdir(docs_dir):
    docs = os.path.join(docs_dir, 'md-meta.html')
    with open(docs, 'w', encoding='utf-8') as f:
        f.write(out)
    print('wrote', docs, len(out), 'bytes')
