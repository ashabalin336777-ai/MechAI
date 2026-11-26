"""Общие хелперы генерации синтетического датасета «Цифровой механик» (всё синтетическое)."""
import json, re, os, copy
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # .../agent_data
ROOT = os.path.dirname(BASE)                                          # .../hackathon
CHUNKS = os.path.join(BASE, 'manuals', 'chunks.jsonl') if os.path.exists(os.path.join(BASE, 'manuals', 'chunks.jsonl')) else os.path.join(ROOT, 'manuals', 'chunks.jsonl')

SYN_NOTE = ("СИНТЕТИЧЕСКИЕ ДАННЫЕ для демонстрации на хакатоне «ИИкузница». Все ТС, номера, VIN, ФИО, "
            "даты, измерения и номера запчастей вымышлены; значения НЕ предназначены для реального ремонта.")

def load_chunks():
    rows = [json.loads(l) for l in open(CHUNKS, encoding='utf-8')]
    return {(r['doc_id'], r['page_id']): r for r in rows}

CH = load_chunks()
SR, SB, RTO = 'СР-ISF28-ДЕМО', 'СБ-ISF28-ДЕМО-01', 'РТО-ГН-ДЕМО'

def norm_ws(s):
    return re.sub(r'\s+', ' ', s).strip()

def cite(doc, page, quote, claim=None):
    """Цитата: проверяется, что страница существует, а quote — дословный фрагмент текста страницы."""
    r = CH[(doc, page)]
    assert norm_ws(quote) in norm_ws(r['text']), f'quote not found in {doc} {page}: {quote!r}'
    d = {'doc_id': doc, 'page_id': page, 'printed_page': r['printed_page'],
         'doc_revision': r['revision'], 'quote': quote}
    if claim: d['claim'] = claim
    return d

# ---- нормы времени и каталог запчастей, разобранные из руководства ----
def _parse_tables():
    works, parts = {}, {}
    for pid in ('14-01', '14-02'):
        for line in CH[(SR, pid)]['text'].split('\n'):
            p = [x.strip() for x in line.split(' | ')]
            if len(p) >= 3 and re.match(r'^[A-Z]{2}-\d{3}$', p[0]):
                h = p[2]
                works[p[0]] = (p[1], None if not re.match(r'^\d+(,\d+)?$', h) else float(h.replace(',', '.')))
    works['DF-001'] = ('Дефектовка шатунно-поршневой группы с составлением акта', 2.5)
    works['DF-002'] = ('Дефектовка блока и ГБЦ', 3.0)
    works['DF-003'] = ('Оформление заявки ТОиР', 0.3)
    for pid in ('14-04', '14-05'):
        for line in CH[(SR, pid)]['text'].split('\n'):
            p = [x.strip() for x in line.split(' | ')]
            if len(p) >= 3 and p[0].startswith('ДМ-ISF28-'):
                parts[p[0]] = p[1]
    return works, parts
WORKS, PARTS = _parse_tables()
WORK_PAGE = {k: ('14-02' if k[:2] in ('CR', 'VT', 'TM', 'EN', 'DF') and k not in ('VT-001', 'VT-002') else '14-01') for k in WORKS}

def work(code, qty=1, coef=1.0, **extra):
    name, h = WORKS[code]
    d = {'code': code, 'name': name, 'qty': qty, 'norm_hours': h, 'norm_source': f'{SR}, стр. {WORK_PAGE[code]}'}
    if h is not None:
        d['norm_hours_adjusted'] = round(h * qty * coef, 2)
    d.update(extra)
    return d

def part(no, qty, **extra):
    d = {'part_no': no, 'name': PARTS[no], 'qty': qty, 'catalog': f'{SR}, стр. ' + ('14-04' if no < 'ДМ-ISF28-0600' else '14-05')}
    d.update(extra)
    return d

def dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write('\n')

def P(*a): return os.path.join(BASE, *a)

# ---- Идентификация парка (все вымышлено) ----
RESP_NSK02 = {'user_id': 'TOIR-002', 'name': 'Орлова Марина Викторовна', 'role': 'ответственный за ТОиР'}
RESP_NSK03 = {'user_id': 'TOIR-003', 'name': 'Волков Игорь Петрович', 'role': 'ответственный за ТОиР'}
MECH = {
  'MECH-007': {'user_id': 'MECH-007', 'name': 'Петров Сергей Николаевич', 'role': 'механик'},
  'MECH-009': {'user_id': 'MECH-009', 'name': 'Кузнецов Дмитрий Андреевич', 'role': 'механик'},
  'MECH-012': {'user_id': 'MECH-012', 'name': 'Лебедев Артём Игоревич', 'role': 'механик'},
}
VEH = {
 'S1': dict(vehicle_id='LCV-NSK-0112', engine_id='ENG-ISF28-0112', vin='X96A21R22K0000112', plate='В112КМ 154', year=2021, km=268000, hours=5860, fleet='FLEET-CARGO-NSK-02', mech='MECH-007', depot='Депо Новосибирск-2', shop='Сервисная зона Новосибирск-2', resp=RESP_NSK02),
 'S2': dict(vehicle_id='LCV-NSK-0127', engine_id='ENG-ISF28-0127', vin='X96A21R22K0000127', plate='Е127ТХ 154', year=2022, km=142300, hours=3420, fleet='FLEET-CARGO-NSK-02', mech='MECH-007', depot='Депо Новосибирск-2', shop='Сервисная зона Новосибирск-2', resp=RESP_NSK02),
 'S3': dict(vehicle_id='LCV-NSK-0089', engine_id='ENG-ISF28-0089', vin='X96A21R22K0000089', plate='Н089АС 154', year=2024, km=78600, hours=1890, fleet='FLEET-CARGO-NSK-03', mech='MECH-012', depot='Депо Новосибирск-3', shop='Сервисная зона Новосибирск-3', resp=RESP_NSK03),
 'S4': dict(vehicle_id='LCV-NSK-0134', engine_id='ENG-ISF28-0134', vin='X96A21R22K0000134', plate='О134РУ 154', year=2020, km=203500, hours=4610, fleet='FLEET-CARGO-NSK-02', mech='MECH-009', depot='Депо Новосибирск-2', shop='Сервисная зона Новосибирск-2', resp=RESP_NSK02),
 'S5': dict(vehicle_id='LCV-NSK-0151', engine_id='ENG-ISF28-0151', vin='X96A21R22K0000151', plate='С151ХМ 154', year=2023, km=119800, hours=2840, fleet='FLEET-CARGO-NSK-03', mech='MECH-012', depot='Депо Новосибирск-3', shop='Сервисная зона Новосибирск-3', resp=RESP_NSK03),
}
ENGINE_CODE = 'ISF2.8s4R148'
ML_IDS = {
 'S1': 'e3a55b90-41c8-4a6f-b2d1-0c9f77a1d2f1',
 'S2': '5b0c7d3a-92e4-4c58-8f1a-3d6e0b4a7c22',
 'S3': 'a91f4e62-0d37-4b85-9c2e-71b8d5f03a43',
 'S4': 'c27d8b19-6e50-4f3a-a4d7-9e1b2c8f5d64',
 'S5': '1f6a93c4-b7d2-45e0-8a39-6c4e0d2b9f85',
}
