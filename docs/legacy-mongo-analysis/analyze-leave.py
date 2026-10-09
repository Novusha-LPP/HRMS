"""Read-only audit of legacy leave policy/quota exports and source user references."""
import collections
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent


def oid(value):
    return value.get('$oid') if isinstance(value, dict) else value


files = {name: ROOT / f'exim.{name}.json' for name in ['leavequotas', 'leavepolicies', 'users']}
data = {name: json.loads(path.read_text()) for name, path in files.items()}
quotas, policies = data['leavequotas'], data['leavepolicies']
users = {oid(r['_id']): r for r in data['users']}
policy_map = {oid(r['_id']): r for r in policies}
refs = [(oid(u['_id']), oid(pid)) for u in data['users']
        for pid in (u.get('leave_settings') or {}).get('special_leave_policies', [])]
ids = {oid(r['driver_id']) for r in quotas}
active = [r for r in policies if r['status'] == 'active']
duplicate_keys = collections.Counter((oid(r['driver_id']), r['leave_type'], r['year']) for r in quotas)
duplicate_policies = collections.Counter((oid(r['company_id']), r['leave_code']) for r in active)
summary = {
    'scope': 'Local exports only; no database migration or mutation.',
    'source_fingerprints': {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files.items()},
    'quotas': {
        'documents': len(quotas), 'drivers': len(ids),
        'years': dict(collections.Counter(r['year'] for r in quotas)),
        'types': {kind: {
            'records': sum(r['leave_type'] == kind for r in quotas),
            'allocated': sum(r['total_days'] for r in quotas if r['leave_type'] == kind),
            'used': sum(r['used_days'] for r in quotas if r['leave_type'] == kind),
            'remaining': sum(r['total_days'] - r['used_days'] for r in quotas if r['leave_type'] == kind),
        } for kind in sorted({r['leave_type'] for r in quotas})},
        'total_days': sum(r['total_days'] for r in quotas),
        'used_days': sum(r['used_days'] for r in quotas),
        'remaining_days': sum(r['total_days'] - r['used_days'] for r in quotas),
        'duplicate_ids': len(quotas) - len({oid(r['_id']) for r in quotas}),
        'duplicate_driver_type_year': [list(key) + [count] for key, count in duplicate_keys.items() if count > 1],
        'invalid_balances': sum(r['used_days'] < 0 or r['total_days'] < 0 or r['used_days'] > r['total_days'] for r in quotas),
        'matched_source_users': len(ids & users.keys()),
        'source_user_roles': dict(collections.Counter(users[i].get('role') for i in ids if i in users)),
        'users_missing_company': sum(not users[i].get('company_id') for i in ids if i in users),
    },
    'policies': {
        'documents': len(policies), 'companies': len({oid(r['company_id']) for r in policies}),
        'status': dict(collections.Counter(r['status'] for r in policies)),
        'duplicate_ids': len(policies) - len(policy_map),
        'active_duplicate_company_code': [list(key) + [count] for key, count in duplicate_policies.items() if count > 1],
        'active_empty_approval_levels': sum(not r['approval_workflow']['levels'] for r in active),
        'active_explicit_hod_approvals': sum(any(x['approver_role'] == 'HOD' for x in r['approval_workflow']['levels']) for r in active),
        'source_users_with_explicit_policy_refs': len({uid for uid, _ in refs}),
        'source_policy_references': len(refs),
        'unresolved_refs': [{'user_id': uid, 'policy_id': pid} for uid, pid in refs if pid not in policy_map],
        'inactive_refs': [{'user_id': uid, 'policy_id': pid} for uid, pid in refs if pid in policy_map and policy_map[pid]['status'] != 'active'],
        'cross_company_refs': [{'user_id': uid, 'user_company_id': oid(users[uid].get('company_id')), 'policy_id': pid, 'policy_company_id': oid(policy_map[pid]['company_id'])} for uid, pid in refs if pid in policy_map and oid(users[uid].get('company_id')) != oid(policy_map[pid]['company_id'])],
        'definitions': [{**r, 'explicit_user_references': sum(pid == oid(r['_id']) for _, pid in refs)} for r in policies],
    },
}
path = OUT / 'leave-summary.json'
path.write_text(json.dumps(summary, indent=2) + '\n')
print(f'Checked {len(quotas)} quotas and {len(policies)} policies; wrote {path}')
