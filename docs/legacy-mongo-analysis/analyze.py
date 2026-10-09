"""Read-only audit of the three legacy MongoDB exports; standard library only."""
import collections
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

def unwrap(value):
    if isinstance(value, dict):
        for key in ('$oid', '$date', '$numberLong'):
            if key in value:
                return unwrap(value[key])
    return value

def date(value):
    value = unwrap(value)
    if isinstance(value, str) and value.lstrip('-').isdigit():
        return dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(milliseconds=int(value))
    return dt.datetime.fromisoformat(value.replace('Z', '+00:00'))

def counts(rows, field):
    return dict(collections.Counter(str(unwrap(r.get(field))) for r in rows))

names = ['weekoffpolicies', 'holidaypolicies', 'attendancepunches']
data = {name: json.loads((ROOT / f'exim.{name}.json').read_text()) for name in names}
punches = data['attendancepunches']
groups = collections.defaultdict(list)
events = collections.defaultdict(list)
employee_companies = collections.defaultdict(set)
for r in punches:
    company, employee = unwrap(r['company_id']), unwrap(r['employee_id'])
    groups[(company, employee, r['punch_date_str'])].append(r)
    events[(company, employee, unwrap(r['punch_time']), r['punch_type'])].append(r)
    employee_companies[employee].add(company)
patterns = collections.Counter(' '.join(r['punch_type'] for r in sorted(rows, key=lambda r: date(r['punch_time']))) for rows in groups.values())
summary = {
    'scope': 'Three supplied JSON exports only; no live database connection or writes.',
    'collections': {name: {'documents': len(rows), 'field_presence': dict(collections.Counter(k for r in rows for k in r)), 'duplicate_ids': len(rows)-len({unwrap(r['_id']) for r in rows})} for name, rows in data.items()},
    'attendance': {
        'employees': len(employee_companies), 'companies': len(counts(punches, 'company_id')),
        'employee_company_days': len(groups),
        'utc_range': [min(unwrap(r['punch_time']) for r in punches), max(unwrap(r['punch_time']) for r in punches)],
        'counts': {f: counts(punches, f) for f in ['company_id', 'punch_type', 'punch_method', 'is_valid', 'is_regularized']},
        'monthly_punches': dict(sorted(collections.Counter(r['punch_date_str'][:7] for r in punches).items())),
        'day_group_sizes': dict(sorted(collections.Counter(len(rows) for rows in groups.values()).items())),
        'top_day_sequences': patterns.most_common(15),
        'duplicate_event_groups': sum(len(rows)>1 for rows in events.values()),
        'excess_duplicate_events': sum(len(rows)-1 for rows in events.values()),
        'max_event_multiplicity': max(map(len, events.values())),
        'punch_date_utc_day_mismatches': sum(date(r['punch_date']).date().isoformat()!=r['punch_date_str'] for r in punches),
        'punch_time_utc_day_mismatches': sum(date(r['punch_time']).date().isoformat()!=r['punch_date_str'] for r in punches),
        'punch_time_ist_day_mismatches': sum(date(r['punch_time']).astimezone(IST).date().isoformat()!=r['punch_date_str'] for r in punches),
        'punch_date_time_components': dict(collections.Counter(date(r['punch_date']).time().isoformat() for r in punches)),
        'employees_in_multiple_companies': sum(len(c)>1 for c in employee_companies.values()),
        'nonempty_validation_errors': sum(bool(r['validation_errors']) for r in punches),
        'single_punch_days_before_last_export_day': sum(len(rows)==1 and key[2]<max(r['punch_date_str'] for r in punches) for key, rows in groups.items()),
        'largest_day_groups': [{'company_id': k[0], 'employee_id': k[1], 'day': k[2], 'punches': len(rows), 'distinct_times': len({unwrap(r['punch_time']) for r in rows}), 'methods': counts(rows, 'punch_method')} for k, rows in sorted(groups.items(), key=lambda item: -len(item[1]))[:5]],
    },
    'weekoff_policies': [{k: r.get(k) for k in ['_id', 'policy_name', 'company_id', 'policy_type', 'applicability', 'day_rules', 'status']} for r in data['weekoffpolicies']],
    'holiday_policies': [{'id': unwrap(r['_id']), 'name': r['policy_name'], 'company_id': unwrap(r['company_id']), 'year': r['year'], 'status': r['status'], 'applicability': r['applicability'], 'holiday_count': len(r['holidays']), 'holidays': [{'name': h['holiday_name'], 'date': date(h['holiday_date']).date().isoformat(), 'year_matches_policy': date(h['holiday_date']).year==r['year'], 'optional': h['is_optional'], 'type': h['holiday_type']} for h in r['holidays']]} for r in data['holidaypolicies']],
}
(OUT / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
print(f"Audited {len(punches):,} punches; wrote {OUT / 'summary.json'}")
