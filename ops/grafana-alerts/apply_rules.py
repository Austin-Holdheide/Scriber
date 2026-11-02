#!/usr/bin/env python3
"""Create/update the Scribly Grafana alert rules from a JSON definition file.

Idempotent: matches on (folderUID, ruleGroup, title) and PUTs if present,
POSTs if not. Pass --dry-run to print what would change.

    python3 apply_rules.py scriberly-credentials            # live
    python3 apply_rules.py --dry-run
"""
import json
import sys
import urllib.parse
import urllib.request
import base64
import os

GRAFANA = os.environ.get('GRAFANA_URL', 'http://192.168.1.106:3000')
GRAFANA_USER = os.environ.get('GRAFANA_USER', 'admin')
GRAFANA_PASS = os.environ['GRAFANA_PASS']
FOLDER_UID = 'scriberly'
FOLDER_TITLE = 'Scribly'
RULE_GROUP = 'scribers-app'
RULE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scribers-app-rules.json')
PROM_UID = 'cfy2ftwhr8lxca'

AUTH = 'Basic ' + base64.b64encode(f'{GRAFANA_USER}:{GRAFANA_PASS}'.encode()).decode()


def api(path, method='GET', payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(GRAFANA + path, data=data, method=method,
                                headers={'Authorization': AUTH, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode()
    return json.loads(body) if body.strip() else None


def build(spec):
    title = spec['title']
    return {
        'uid': spec.get('uid'),
        'title': title,
        'ruleGroup': RULE_GROUP,
        'folderUID': FOLDER_UID,
        'orgID': 1,
        'condition': 'B',
        'data': [
            {
                'refId': 'A',
                'queryType': '',
                'relativeTimeRange': {'from': 600, 'to': 0},
                'datasourceUid': PROM_UID,
                'model': {
                    'editorMode': 'code',
                    'expr': spec['expr'],
                    'instant': True,
                    'intervalMs': 1000,
                    'legendFormat': '{{instance}}',
                    'maxDataPoints': 43200,
                    'range': False,
                    'refId': 'A',
                },
            },
            {
                'refId': 'B',
                'queryType': '',
                'relativeTimeRange': {'from': 0, 'to': 0},
                'datasourceUid': '__expr__',
                'model': {
                    'conditions': [{
                        'evaluator': {'params': [spec['threshold']['param']], 'type': spec['threshold']['type']},
                        'operator': {'type': 'and'},
                        'query': {'params': []},
                        'reducer': {'params': [], 'type': 'last'},
                    }],
                    'expression': 'A',
                    'intervalMs': 1000,
                    'maxDataPoints': 43200,
                    'refId': 'B',
                    'type': 'threshold',
                },
            },
        ],
        'noDataState': 'OK',
        'execErrState': 'Error',
        'for': spec['for'],
        'keep_firing_for': '0s',
        'isPaused': False,
        'annotations': {'summary': spec['summary'], 'description': spec['description']},
        'labels': {'team': 'scriberly', 'severity': spec['severity'], 'stack': 'scriber'},
    }


def main():
    dry = '--dry-run' in sys.argv
    specs = json.load(open(RULE_FILE))

    existing = {(r['folderUID'], r['ruleGroup'], r['title']): r for r in api('/api/v1/provisioning/alert-rules')}

    for spec in specs:
        payload = build(spec)
        key = (FOLDER_UID, RULE_GROUP, spec['title'])
        cur = existing.get(key)
        if cur:
            payload['uid'] = cur['uid']
            print(('UPDATE  ' if not dry else 'would UPDATE ') + spec['title'])
            if not dry:
                api(f"/api/v1/provisioning/alert-rules/{cur['uid']}", 'PUT', payload)
        else:
            print(('CREATE  ' if not dry else 'would CREATE ') + spec['title'])
            if not dry:
                api('/api/v1/provisioning/alert-rules', 'POST', payload)

    if not dry:
        print('\n--- rules now in folder', FOLDER_UID)
        for r in api('/api/v1/provisioning/alert-rules'):
            if r['folderUID'] == FOLDER_UID:
                print(f"  {r['ruleGroup']:14s} {r['title']:40s} for={r['for']:5s} {r['labels'].get('severity')}")


if __name__ == '__main__':
    main()
