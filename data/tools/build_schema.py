"""Строит схему ML-сервиса v1.1 на основе v1.0 (ml_service_schema.json)."""
import json, copy
from common import *

src = json.load(open(os.path.join(BASE, 'ml_service_schema_v1.0.json'), encoding='utf-8'))
js = copy.deepcopy(src['json_schema'])
js['$id'] = 'https://hackathon.local/schemas/engine-diagnostics-ml-v1.1.json'
props = js['properties']
props['schema_version'] = {'type': 'string', 'const': '1.1.0'}
# --- метаданные синтетики (необязательные) ---
props['meta'] = {
  'type': 'object', 'additionalProperties': False,
  'description': 'Служебные метаданные заглушки (v1.1). Реальный ML-сервис может их не отдавать.',
  'properties': {
    'synthetic': {'type': 'boolean'},
    'scenario_id': {'type': 'string'},
    'note': {'type': 'string'}}}
# --- analysis.trigger ---
props['analysis']['properties']['trigger'] = {
  'type': 'string', 'enum': ['driver_complaint', 'scheduled_check', 'mechanic_request', 'post_repair_check'],
  'description': 'Что инициировало запись (v1.1).'}
# --- quality.rerecord_instructions ---
q = props['recording']['properties']['quality']['properties']
q['rerecord_instructions'] = {'type': 'array', 'items': {'type': 'string'},
  'description': 'Как повторить запись, если качество не подошло (v1.1). Критерии см. СР-ISF28-ДЕМО стр. 12-02, 12-07.'}
# --- overall: недиагностируемый результат ---
o = props['overall']['properties']
o['severity']['enum'] = ['normal', 'attention', 'warning', 'critical', 'undetermined']
o['urgency']['enum'] = ['can_operate', 'inspect_this_week', 'inspect_immediately', 'do_not_operate', 'recording_invalid']
o['urgency']['description'] = ("recording_invalid (v1.1): запись непригодна (quality.status=rejected), зона и срочность "
                               "не определены; нужна повторная запись. Это НЕ равно can_operate.")
o['requires_rerecord'] = {'type': 'boolean', 'description': 'v1.1: ML-сервис просит повторить запись.'}
# fault severity тоже получает undetermined для согласованности
props['faults']['items']['properties']['severity']['enum'] = ['normal', 'attention', 'warning', 'critical', 'undetermined']

out = {
  '$comment': src['$comment'] + ' v1.1 — добавлены: meta, analysis.trigger, quality.rerecord_instructions, '
              'overall.requires_rerecord, severity=undetermined, urgency=recording_invalid. Обратно совместимо с v1.0 по остальным полям.',
  'schema_version': '1.1.0',
  'changelog': {
    '1.1.0': [
      'schema_version: const 1.1.0',
      'meta{synthetic,scenario_id,note}: пометка синтетических данных',
      'analysis.trigger: причина анализа',
      'recording.quality.rerecord_instructions: инструкции по повторной записи',
      'overall.requires_rerecord (bool)',
      'overall.severity / faults[].severity: добавлено значение undetermined',
      'overall.urgency: добавлено значение recording_invalid (запись непригодна — не диагностировать)']},
  'json_schema': js,
  'examples': []}
# примеры v1.0 переносим, меняя только версию (все они должны проходить валидацию v1.1)
def _neutral(o):
    if isinstance(o, str): return o.replace('ГАЗель Next', 'LCV-3.5t')
    if isinstance(o, list): return [_neutral(x) for x in o]
    if isinstance(o, dict): return {k: _neutral(v) for k, v in o.items()}
    return o
for ex in src['examples']:
    e = _neutral(copy.deepcopy(ex)); e['schema_version'] = '1.1.0'; out['examples'].append(e)
dump(P('ml_service_schema_v1.1.json'), out)
dump(P('schema', 'ml_response.schema.v1.1.json'), js)
print('ok')
