"""Проверка датасета: схема ML v1.1, цитаты, коды работ/запчастей, согласованность между файлами."""
import json, glob, sys, re
from jsonschema import Draft202012Validator, FormatChecker
from common import *

errors = []
def err(m): errors.append(m)
def load(*p): return json.load(open(P(*p), encoding='utf-8'))

# 1. ML JSON ↔ схема v1.1
schema = load('schema', 'ml_response.schema.v1.1.json')
Draft202012Validator.check_schema(schema)
val = Draft202012Validator(schema, format_checker=FormatChecker())
mls = {}
for f in sorted(glob.glob(P('ml_responses', '*.json'))):
    d = json.load(open(f, encoding='utf-8')); mls[d['meta']['scenario_id']] = d
    for e in val.iter_errors(d): err(f'ML {os.path.basename(f)}: {list(e.path)} {e.message[:120]}')
wrapper = load('ml_service_schema_v1.1.json')
for ex in wrapper['examples']:
    ex = {k: v for k, v in ex.items() if k != 'title'}
    for e in val.iter_errors(ex): err(f'schema example: {list(e.path)} {e.message[:120]}')
assert set(mls) == {'S1', 'S2', 'S3', 'S4', 'S5'}, mls.keys()

# 2. Зоны / срочность ML согласованы с 12-03 / 12-04
def zone(rms, g):
    z = lambda x, b: 'A' if x < b[0] else 'B' if x < b[1] else 'C' if x <= b[2] else 'D'
    zr = z(rms, (2.8, 7.1, 11.2)); zg = z(g, (1.5, 3.0, 4.0))
    return max(zr, zg)
URG = {'A': 'can_operate', 'B': 'can_operate', 'C': 'inspect_this_week', 'D': 'do_not_operate'}
for s, d in mls.items():
    o = d['overall']
    if 'overall_vibration' in o:
        v = o['overall_vibration']; z = zone(v['rms_velocity_mm_s'], v['peak_acceleration_g'])
        if z != o['severity_zone']: err(f'{s}: zone {o["severity_zone"]} != {z} по RMS/пику')
        if URG[z] != o['urgency']: err(f'{s}: urgency {o["urgency"]} != {URG[z]}')
    if d['recording']['quality']['status'] == 'rejected' and not (o['verdict'] == 'uncertain' and o['requires_rerecord']):
        err(f'{s}: rejected без uncertain/requires_rerecord')
    v = d['vehicle']; vv = VEH[s]
    if (v['vehicle_id'], v['vin'], v['license_plate'], v['mileage_km'], v['operating_hours'], v['engine']['id']) != (vv['vehicle_id'], vv['vin'], vv['plate'], vv['km'], vv['hours'], vv['engine_id']):
        err(f'{s}: ML vehicle не совпадает с VEH')
    if d['analysis']['analysis_id'] != ML_IDS[s]: err(f'{s}: analysis_id')
    for f in d['faults']:
        if f['code'] in ('timing_chain_stretch', 'timing_belt_wear') : err(f'{s}: неприменимый класс')
if mls['S1']['overall']['severity_zone'] != 'D' or mls['S1']['vehicle']['mileage_km'] != 268000: err('S1 spec')
if dict((p['name'], p['value']) for p in mls['S1']['obd']['pids'])['oil_pressure'] != 1.6: err('S1 oil 1.6')
if mls['S2']['overall']['severity_zone'] != 'C' or mls['S3']['overall']['severity_zone'] != 'B': err('S2/S3 zone')
if mls['S4']['overall']['verdict'] != 'uncertain': err('S4 verdict')

# 3. Карточки и история
cards = load('engine_cards.json')['cards']; cmap = {c['scenario_id']: c for c in cards}
hist = load('defect_history.json')['by_engine']
for s, c in cmap.items():
    vv = VEH[s]
    if (c['vehicle_id'], c['vin'], c['license_plate'], c['mileage_km'], c['operating_hours'], c['engine']['engine_id']) != (vv['vehicle_id'], vv['vin'], vv['plate'], vv['km'], vv['hours'], vv['engine_id']):
        err(f'card {s} mismatch')
    if len(c['vin']) != 17: err(f'{s}: VIN len')
    if not re.match(r'^[АВЕКМНОРСТУХ]\d{3}[АВЕКМНОРСТУХ]{2} \d{2,3}$', c['license_plate']): err(f'{s}: plate format {c["license_plate"]}')
    h = hist[vv['engine_id']]['records']
    if max(r['mileage_km'] for r in h) > vv['km']: err(f'{s}: история с пробегом > текущего')
    dates = [r['date'] for r in h]
    if dates != sorted(dates): err(f'{s}: история не по порядку')
    kms = [r['mileage_km'] for r in h]
    if kms != sorted(kms): err(f'{s}: пробег в истории немонотонен')
    for r in h:
        for w in r['works']:
            if w['code'] not in WORKS: err(f'{s} hist work {w["code"]}')
            elif WORKS[w['code']][1] != w['norm_hours']: err(f'{s} hist work norm {w["code"]}')
        for p in r['parts']:
            if p['part_no'] not in PARTS: err(f'{s} hist part {p["part_no"]}')
    # дата последнего ТО в карте есть в истории
    lt = c['last_to']
    if not any(r['date'] == lt['date'] and r['mileage_km'] == lt['mileage_km'] for r in h): err(f'{s}: last_to нет в истории')
    if c['oil']['last_change_mileage_km'] != lt['mileage_km']: err(f'{s}: oil last change != last_to')
    if c['oil']['last_change_mileage_km'] > vv['km']: err(f'{s}: oil km')
if cmap['S2']['fuel_filter_last_change'] is not None: err('S2 fuel filter должен быть null')
if not any(r['date'] == '2026-09-19' and r['dtcs'] for r in hist[VEH['S1']['engine_id']]['records']): err('S1 hint missing')

# 4. Заявки: цитаты, коды, нормы, согласованность
REQ = {}
for f in sorted(glob.glob(P('defect_requests', '*.json'))):
    r = json.load(open(f, encoding='utf-8')); REQ[os.path.basename(f)] = r
TEMPLATE = ['request_id', 'created_at', 'vehicle', 'engine', 'request_type', 'priority', 'urgency', 'operation_ban', 'ml_analysis_id', 'fault', 'symptoms', 'measurements',
            'manual_refs', 'work_items', 'parts', 'estimated_norm_hours', 'bulletins', 'requested_by', 'confirmed_by', 'confirmed_at', 'status']
for name, r in REQ.items():
    s = r['scenario_id']; vv = VEH[s]
    for k in TEMPLATE:
        if k not in r: err(f'{name}: нет поля {k}')
    if r['vehicle']['vehicle_id'] != vv['vehicle_id'] or r['vehicle']['mileage_km'] != vv['km']: err(f'{name}: vehicle')
    if r['ml_analysis_id'] != ML_IDS[s]: err(f'{name}: ml id')
    if r['request_type'] not in ('defect_inspection', 'repair', 'scheduled_maintenance'): err(f'{name}: request_type')
    if r['priority'] not in ('low', 'normal', 'high', 'critical'): err(f'{name}: priority')
    if r['urgency'] != mls[s]['overall']['urgency']: err(f'{name}: urgency != ML')
    for ref in r['manual_refs']:
        row = CH.get((ref['doc_id'], ref['page_id']))
        if row is None: err(f'{name}: нет страницы {ref["doc_id"]} {ref["page_id"]}'); continue
        if norm_ws(ref['quote']) not in norm_ws(row['text']): err(f'{name}: цитата не найдена {ref["page_id"]}: {ref["quote"][:50]}')
        if ref['printed_page'] != row['printed_page']: err(f'{name}: printed_page')
    for h in r['diagnosis_hypotheses']:
        for mr in h['manual_refs']:
            m = re.match(r'^(.+) (\d\d-\d\d)$', mr)
            if not m or (m.group(1), m.group(2)) not in CH: err(f'{name}: hypothesis ref {mr}')
    tot = 0
    for w in r['work_items'] + r['conditional_work_items']:
        if w['code'] is None: continue
        if w['code'] not in WORKS or WORKS[w['code']][1] != w['norm_hours']: err(f'{name}: work {w["code"]}')
    for w in r['work_items']:
        if w['code'] is not None and w['norm_hours'] is not None: tot += w['norm_hours_adjusted']
    coef = r['norm_hours_coefficient']['value']
    exp_coef = 1.2 if vv['km'] > 250000 else 1.0
    if coef != exp_coef: err(f'{name}: coef')
    for w in r['work_items'] + r['conditional_work_items']:
        if w['code'] and w['norm_hours'] is not None and abs(w['norm_hours_adjusted'] - round(w['norm_hours'] * w['qty'] * coef, 2)) > 1e-9: err(f'{name}: adj {w["code"]}')
    if abs(round(tot, 2) - r['estimated_norm_hours']) > 1e-9: err(f'{name}: estimated_norm_hours {tot} != {r["estimated_norm_hours"]}')
    for p in r['parts'] + r['conditional_parts']:
        if p['part_no'] not in PARTS or PARTS[p['part_no']] != p['name']: err(f'{name}: part {p["part_no"]}')
    if r['operation_ban'] and not (mls[s]['overall']['severity_zone'] == 'D' or any(m['parameter'].startswith('Давление масла') and m['verdict'] in ('критично', 'эксплуатация запрещена') for m in r['measurements'])): err(f'{name}: ban без оснований')
    ps = [h['agent_posterior'] for h in r['diagnosis_hypotheses']]
    if abs(sum(ps) - 1.0) > 1e-9: err(f'{name}: posterior sum {sum(ps)}')
    if name.endswith('draft.json'):
        if not (r['status'] == 'draft_awaiting_confirmation' and r['confirmed_by'] is None and r['confirmation_token'] is None and r['request_id'] is None): err(f'{name}: draft state')
sub = REQ['S1_confirmed_submitted.json']; dr = REQ['S1_draft.json']
if not (sub['status'] == 'submitted' and sub['confirmed_by'] and sub['confirmation_token'] and sub['confirmed_at'] and sub['request_id']): err('S1 submitted fields')
if sub['confirmed_at'] > sub['submitted_at']: err('S1 confirmed after submit')
for k in ('work_items', 'parts', 'manual_refs', 'estimated_norm_hours', 'fault', 'priority', 'urgency'):
    if sub[k] != dr[k]: err(f'S1 submitted differs in {k}')
if 'S4' in [r['scenario_id'] for r in REQ.values()]: err('S4 не должен иметь заявки')
# бюллетень S1: предел 0,095 и коэффициент 1,2
if sub['estimated_norm_hours'] != 19.56: err('S1 hours')

# 5. Диалоги
dl = load('mechanic_dialogs.json')['dialogs']
for s, d in dl.items():
    if d['engine_id'] != VEH[s]['engine_id']: err(f'dialog {s}')
    ts = [t['at'] for t in d['turns']]
    if ts != sorted(ts): err(f'dialog {s} time order')
    if (s in ('S1', 'S2', 'S4', 'S5')) != bool(d['turns']): err(f'dialog {s}: turns presence')
    if d['turns'] and d['turns'][0]['tool'] != 'ask_mechanic': err(f'dialog {s}: first tool')
a = dl['S1']['turns'][1]['answer_structured']
m = {x['parameter']: x['value'] for x in REQ['S1_draft.json']['measurements']}
if a['oil_pressure_800_bar'] != m['Давление масла, 800 об/мин, прогретый'] or a['oil_pressure_1500_bar'] != m['Давление масла, 1 500 об/мин, прогретый']: err('S1 dialog vs request')
if dl['S1']['after_draft']['confirmation_token_issued_by_ui'] != sub['confirmation_token']: err('token mismatch')

# 6. Golden
g = load('golden_scenarios.json')
for sc in g['scenarios']:
    s = sc['scenario_id']
    for c in sc['required_citations']:
        if (c['doc_id'], c['page_id']) not in CH: err(f'golden {s}: нет страницы {c}')
    for t in sc['expected_tool_calls']:
        if t['tool'] not in ('get_engine_card', 'get_ml_diagnosis', 'search_manuals', 'get_manual_page', 'get_defect_history', 'ask_mechanic', 'draft_defect_request', 'submit_defect_request'):
            err(f'golden {s}: tool {t["tool"]}')
    if len(sc['expected_tool_calls']) != sc['ideal_tool_calls']: err(f'golden {s}: ideal_tool_calls')
    if sc['ideal_tool_calls'] > 8: err(f'golden {s}: ideal > 8')
    if sc['expected_draft_file']:
        for part in re.findall(r'defect_requests/\S+?\.json', sc['expected_draft_file']):
            if not os.path.exists(P(part)): err(f'golden {s}: file {part}')
    oc = sc['expected_outcome']
    if oc.get('estimated_norm_hours') is not None:
        fr = REQ[f'{s}_draft.json']
        if oc['estimated_norm_hours'] != fr['estimated_norm_hours']: err(f'golden {s}: hours')
        if oc['priority'] != fr['priority'] or oc['urgency'] != fr['urgency'] or oc['request_type'] != fr['request_type']: err(f'golden {s}: outcome vs draft')
    for fl in sc['inputs'].values():
        p = fl.split('#')[0]
        if p.startswith('manuals/'): p = os.path.join('..', p)
        if not os.path.exists(P(p)) and not os.path.exists(os.path.join(ROOT, p)): err(f'golden {s}: input {fl}')

print('ERRORS:', len(errors))
for e in errors: print(' -', e)
sys.exit(1 if errors else 0)
