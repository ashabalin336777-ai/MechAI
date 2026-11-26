from common import *

STD = 'ISO_10816-6_inspired_class5_reciprocating_gt_100kW'
DISCL = ("Вероятностная оценка ML-сервиса, не окончательный диагноз. Решение о ремонте принимает механик после осмотра и "
         "сверки с руководством. Зоны A–D — ориентир по образцу ISO 10816-6 (поршневые машины > 100 кВт), не сертификационный замер. "
         "Синтетические данные для хакатона.")

def vehicle(s):
    v = VEH[s]
    return {'vehicle_id': v['vehicle_id'], 'vin': v['vin'], 'fleet_id': v['fleet'], 'usage': 'lcv',
            'make': 'Синтетический парк', 'model': 'LCV-3.5t', 'generation': None, 'year': v['year'],
            'license_plate': v['plate'],
            'engine': {'id': v['engine_id'], 'code': ENGINE_CODE, 'family': 'ISF2.8', 'fuel': 'diesel', 'displacement_l': 2.8,
                       'cylinders': 4, 'configuration': 'inline', 'rated_power_kw': 110, 'aspiration': 'turbo'},
            'mileage_km': v['km'], 'operating_hours': v['hours']}

def analysis(s, at, trigger):
    return {'analysis_id': ML_IDS[s], 'analyzed_at': at, 'model_id': 'engine-acoustics-clf',
            'model_version': '2026.11-hackathon-stub-v1.1',
            'pipeline': ['spectral_features', 'anomaly_detector', 'fault_classifier', 'severity_zone_mapper'],
            'trigger': trigger}

def meta(s, note):
    return {'synthetic': True, 'scenario_id': s, 'note': 'СИНТЕТИЧЕСКИЕ ДАННЫЕ. ' + note}

R = {}

# ───────────────────────────── S1 critical ─────────────────────────────
R['S1_critical_conrod_knock_cyl3'] = {
 'schema_version': '1.1.0',
 'meta': meta('S1', 'Критический сценарий: стук шатунного подшипника цил. 3, зона D, пробег 268 000 км (применим СБ-ISF28-ДЕМО-01).'),
 'analysis': analysis('S1', '2026-11-18T09:42:10+07:00', 'driver_complaint'),
 'vehicle': vehicle('S1'),
 'recording': {
   'recorded_at': '2026-11-18T09:38:45+07:00', 'duration_s': 25, 'sample_rate_hz': 25600, 'channels': 1,
   'sensor_type': 'accelerometer', 'sensor_position': 'block_below_cylinder_3_oil_pan_area',
   'audio_ref': 'rec://demo/S1/LCV-NSK-0112/2026-11-18T09-38-45.wav',
   'conditions': {'engine_state': 'off_idle', 'engine_speed_rpm': 1450, 'engine_load_pct': 0, 'coolant_temp_c': 88, 'oil_temp_c': 97,
                  'vehicle_speed_kph': 0, 'gear': 'N', 'ambient_temp_c': -6, 'environment': 'depot'},
   'quality': {'status': 'ok', 'snr_db': 24.8, 'rms_dbfs': -21.4, 'silence_ratio': 0.02, 'clipping_ratio': 0.002, 'warnings': []}},
 'overall': {'verdict': 'anomaly', 'anomaly_score': 0.93, 'severity': 'critical', 'severity_zone': 'D', 'severity_standard': STD,
             'urgency': 'do_not_operate', 'confidence': 0.86, 'requires_rerecord': False,
             'overall_vibration': {'rms_velocity_mm_s': 13.9, 'peak_acceleration_g': 4.4, 'frequency_range_hz': [2, 1000]}},
 'faults': [
   {'code': 'conrod_bearing_knock', 'name_ru': 'Стук шатунного подшипника', 'probability': 0.82, 'confidence': 0.86,
    'component': 'connecting_rod_bearing', 'location': {'bank': 1, 'cylinder': 3, 'side': None},
    'frequency_bands': [{'f_low_hz': 300, 'f_high_hz': 2500, 'peak_hz': 724, 'amplitude': 9.8, 'unit': 'mm/s', 'shaft_order': 1.0}],
    'severity': 'critical', 'severity_zone': 'D', 'related_dtcs': ['P1A31'],
    'recommended_checks': ['Остановить эксплуатацию, не нагружать двигатель',
                           'Замерить давление масла механическим манометром на прогретом двигателе на 800 и 1 500 об/мин',
                           'Прослушать нижнюю часть блока стетоскопом, сравнить цилиндры',
                           'Проверить уровень и запах масла (подозрение на разжижение топливом)']},
   {'code': 'injector_fault', 'name_ru': 'Неисправность форсунки', 'probability': 0.10, 'confidence': 0.52,
    'component': 'injector', 'location': {'bank': 1, 'cylinder': 3, 'side': None},
    'frequency_bands': [{'f_low_hz': 3000, 'f_high_hz': 9000, 'peak_hz': 5400, 'amplitude': 1.2, 'unit': 'g', 'shaft_order': 0.5}],
    'severity': 'warning', 'severity_zone': 'C', 'related_dtcs': [],
    'recommended_checks': ['Проверить утечку форсунки цилиндра 3 в обратку и баланс цилиндров — после проверки подшипников']},
   {'code': 'main_bearing_knock', 'name_ru': 'Стук коренного подшипника', 'probability': 0.05, 'confidence': 0.4,
    'component': 'main_bearing', 'location': {'bank': 1, 'cylinder': None, 'side': None},
    'frequency_bands': [{'f_low_hz': 150, 'f_high_hz': 800, 'peak_hz': 310, 'amplitude': 3.1, 'unit': 'mm/s', 'shaft_order': 0.5}],
    'severity': 'attention', 'severity_zone': 'B', 'related_dtcs': [],
    'recommended_checks': ['Проверить осевой зазор коленчатого вала при дефектовке']}],
 'obd': {'mil_on': True,
   'dtcs': [{'code': 'P1A31', 'status': 'active', 'system': 'engine', 'description': 'Нестабильность скорости коленвала цилиндра 3'},
            {'code': 'P0521', 'status': 'pending', 'system': 'engine', 'description': 'Диапазон/производительность датчика давления масла'}],
   'pids': [{'pid': 'J1939-190', 'name': 'engine_rpm', 'value': 1450, 'unit': 'rpm'},
            {'pid': 'J1939-100', 'name': 'oil_pressure', 'value': 1.6, 'unit': 'bar'},
            {'pid': 'J1939-110', 'name': 'coolant_temp', 'value': 88, 'unit': 'C'},
            {'pid': 'J1939-157', 'name': 'rail_pressure', 'value': 342, 'unit': 'bar'}]},
 'recommended_checks': ['Запретить выезд до дефектовки нижней головки шатуна цилиндра 3',
                        'Зафиксировать давление масла, температуру и условия записи в заявке ТОиР',
                        'Подготовить комплект шатунных вкладышей и процедуру измерения шеек',
                        'Взять пробу масла (разжижение топливом, Pb/Cu)'],
 'service_hints': ['Глухой металлический стук в нижней части блока около 3-го цилиндра, сильнее с ростом оборотов',
                   'Давление масла на прогретом моторе ниже нормы — приоритет подшипникам, а не форсунке',
                   'Пробег выше 250 000 км: возможно действуют сервисные бюллетени по износу вкладышей'],
 'disclaimer': DISCL}

# ───────────────────────────── S2 medium / needs clarification ─────────────────────────────
R['S2_medium_injector_misfire_cyl2'] = {
 'schema_version': '1.1.0',
 'meta': meta('S2', 'Средний сценарий: форсунка/пропуски цил. 2, зона C; не хватает записи на холодном пуске и данных о топливе → агент обязан вызвать ask_mechanic.'),
 'analysis': analysis('S2', '2026-11-17T14:21:36+07:00', 'driver_complaint'),
 'vehicle': vehicle('S2'),
 'recording': {
   'recorded_at': '2026-11-17T14:18:20+07:00', 'duration_s': 22, 'sample_rate_hz': 25600, 'channels': 1,
   'sensor_type': 'accelerometer', 'sensor_position': 'cylinder_head_cyl1',
   'audio_ref': 'rec://demo/S2/LCV-NSK-0127/2026-11-17T14-18-20.wav',
   'conditions': {'engine_state': 'idle', 'engine_speed_rpm': 810, 'engine_load_pct': 0, 'coolant_temp_c': 86, 'oil_temp_c': 92,
                  'vehicle_speed_kph': 0, 'gear': 'N', 'ambient_temp_c': -4, 'environment': 'depot'},
   'quality': {'status': 'ok', 'snr_db': 19.3, 'rms_dbfs': -23.7, 'silence_ratio': 0.04, 'clipping_ratio': 0.001,
               'warnings': ['Запись только на прогретом двигателе: холодный пуск не записан, injector_fault / knock_detonation / piston_slap не разделяются',
                            'Запись только на холостом ходу (810 об/мин), контрольной записи на 1 450 об/мин нет',
                            'Нет данных о качестве топлива и дате замены топливного фильтра']}},
 'overall': {'verdict': 'anomaly', 'anomaly_score': 0.61, 'severity': 'warning', 'severity_zone': 'C', 'severity_standard': STD,
             'urgency': 'inspect_this_week', 'confidence': 0.55, 'requires_rerecord': False,
             'overall_vibration': {'rms_velocity_mm_s': 8.4, 'peak_acceleration_g': 3.4, 'frequency_range_hz': [2, 1000]}},
 'faults': [
   {'code': 'injector_fault', 'name_ru': 'Неисправность форсунки', 'probability': 0.46, 'confidence': 0.55,
    'component': 'injector', 'location': {'bank': 1, 'cylinder': 2, 'side': None},
    'frequency_bands': [{'f_low_hz': 3000, 'f_high_hz': 9000, 'peak_hz': 5200, 'amplitude': 1.9, 'unit': 'g', 'shaft_order': 0.5}],
    'severity': 'warning', 'severity_zone': 'C', 'related_dtcs': ['P1A41'],
    'recommended_checks': ['Проверить баланс цилиндров и утечку форсунки цилиндра 2 в обратку',
                           'Сначала исключить причины на стороне низкого давления (фильтр, вода, воздух)']},
   {'code': 'misfire', 'name_ru': 'Пропуски воспламенения', 'probability': 0.34, 'confidence': 0.50,
    'component': 'combustion', 'location': {'bank': 1, 'cylinder': 2, 'side': None},
    'frequency_bands': [{'f_low_hz': 30, 'f_high_hz': 300, 'peak_hz': 48, 'amplitude': 2.7, 'unit': 'mm/s', 'shaft_order': 0.5}],
    'severity': 'warning', 'severity_zone': 'C', 'related_dtcs': ['P0302'],
    'recommended_checks': ['Баланс цилиндров на холостом ходу', 'Проверить давление подкачки и состояние топливного фильтра']},
   {'code': 'knock_detonation', 'name_ru': 'Жёсткое сгорание', 'probability': 0.10, 'confidence': 0.30,
    'component': 'combustion', 'location': {'bank': 1, 'cylinder': 2, 'side': None},
    'frequency_bands': [{'f_low_hz': 1500, 'f_high_hz': 6000, 'peak_hz': 2900, 'amplitude': 0.8, 'unit': 'g', 'shaft_order': 0.5}],
    'severity': 'attention', 'severity_zone': 'B', 'related_dtcs': [],
    'recommended_checks': ['Сделать запись на холодном пуске, чтобы подтвердить или исключить']},
   {'code': 'fuel_pump', 'name_ru': 'ТНВД / подача топлива', 'probability': 0.05, 'confidence': 0.25,
    'component': 'high_pressure_pump', 'location': {'bank': None, 'cylinder': None, 'side': None},
    'frequency_bands': [{'f_low_hz': 500, 'f_high_hz': 4000, 'peak_hz': 1100, 'amplitude': 0.6, 'unit': 'g', 'shaft_order': 0.5}],
    'severity': 'attention', 'severity_zone': 'B', 'related_dtcs': [], 'recommended_checks': ['Проверить давление в рампе и подкачки']}],
 'obd': {'mil_on': False,
   'dtcs': [{'code': 'P0302', 'status': 'pending', 'system': 'engine', 'description': 'Пропуск воспламенения в цилиндре 2'},
            {'code': 'P1A41', 'status': 'pending', 'system': 'engine', 'description': 'Превышение коррекции подачи цилиндра'}],
   'pids': [{'pid': 'J1939-190', 'name': 'engine_rpm', 'value': 810, 'unit': 'rpm'},
            {'pid': 'J1939-100', 'name': 'oil_pressure', 'value': 1.4, 'unit': 'bar'},
            {'pid': 'J1939-157', 'name': 'rail_pressure', 'value': 318, 'unit': 'bar'},
            {'pid': None, 'name': 'cyl2_fuel_correction', 'value': 3.4, 'unit': 'mm3/stroke'}]},
 'recommended_checks': ['Записать двигатель на холодном пуске (масло < 40 °C) для разделения injector_fault / knock_detonation',
                        'Баланс цилиндров и утечка форсунок в обратку',
                        'Уточнить у механика дату замены топливного фильтра, наличие воды в отстое и качество последней заправки'],
 'service_hints': ['Щелчки одного цилиндра на холостом, коррекция подачи цилиндра 2 вне нормы',
                   'Уверенность средняя: нужны холодная запись и контекст по топливу'],
 'disclaimer': DISCL}

# ───────────────────────────── S3 low / planned ─────────────────────────────
R['S3_low_valve_clearance_zoneB'] = {
 'schema_version': '1.1.0',
 'meta': meta('S3', 'Низкий сценарий: шум клапанов (valve_clearance), зона B → в плановое ТО, срочной заявки нет. В ответе присутствует неприменимый класс hydraulic_lifter (ошибка классификации).'),
 'analysis': analysis('S3', '2026-11-16T08:07:14+07:00', 'scheduled_check'),
 'vehicle': vehicle('S3'),
 'recording': {
   'recorded_at': '2026-11-16T08:04:02+07:00', 'duration_s': 25, 'sample_rate_hz': 25600, 'channels': 1,
   'sensor_type': 'accelerometer', 'sensor_position': 'cylinder_head_cyl1',
   'audio_ref': 'rec://demo/S3/LCV-NSK-0089/2026-11-16T08-04-02.wav',
   'conditions': {'engine_state': 'off_idle', 'engine_speed_rpm': 1460, 'engine_load_pct': 0, 'coolant_temp_c': 90, 'oil_temp_c': 94,
                  'vehicle_speed_kph': 0, 'gear': 'N', 'ambient_temp_c': -7, 'environment': 'depot'},
   'quality': {'status': 'ok', 'snr_db': 21.2, 'rms_dbfs': -22.9, 'silence_ratio': 0.03, 'clipping_ratio': 0.0, 'warnings': []}},
 'overall': {'verdict': 'anomaly', 'anomaly_score': 0.27, 'severity': 'attention', 'severity_zone': 'B', 'severity_standard': STD,
             'urgency': 'can_operate', 'confidence': 0.78, 'requires_rerecord': False,
             'overall_vibration': {'rms_velocity_mm_s': 4.1, 'peak_acceleration_g': 2.2, 'frequency_range_hz': [2, 1000]}},
 'faults': [
   {'code': 'valve_clearance', 'name_ru': 'Тепловые зазоры клапанов', 'probability': 0.66, 'confidence': 0.74,
    'component': 'valve_train', 'location': {'bank': 1, 'cylinder': None, 'side': None},
    'frequency_bands': [{'f_low_hz': 2000, 'f_high_hz': 6000, 'peak_hz': 3800, 'amplitude': 1.4, 'unit': 'g', 'shaft_order': 0.5}],
    'severity': 'attention', 'severity_zone': 'B', 'related_dtcs': [],
    'recommended_checks': ['Проверить тепловые зазоры клапанов щупом на холодном двигателе', 'Повторить запись после регулировки']},
   {'code': 'normal', 'name_ru': 'Норма', 'probability': 0.17, 'confidence': 0.6,
    'component': 'engine', 'location': {'bank': None, 'cylinder': None, 'side': None},
    'severity': 'normal', 'severity_zone': 'A', 'related_dtcs': [], 'recommended_checks': []},
   {'code': 'hydraulic_lifter', 'name_ru': 'Гидрокомпенсаторы', 'probability': 0.09, 'confidence': 0.2,
    'component': 'valve_train', 'location': {'bank': 1, 'cylinder': None, 'side': None},
    'frequency_bands': [{'f_low_hz': 2000, 'f_high_hz': 6000, 'peak_hz': 3500, 'amplitude': 0.7, 'unit': 'g', 'shaft_order': 0.5}],
    'severity': 'attention', 'severity_zone': 'B', 'related_dtcs': [],
    'recommended_checks': ['Проверить клапанный механизм']},
   {'code': 'accessory_drive', 'name_ru': 'Привод навесного оборудования', 'probability': 0.08, 'confidence': 0.3,
    'component': 'accessory_belt', 'location': {'bank': None, 'cylinder': None, 'side': 'front'},
    'frequency_bands': [{'f_low_hz': 2000, 'f_high_hz': 6000, 'peak_hz': 2400, 'amplitude': 0.5, 'unit': 'g', 'shaft_order': None}],
    'severity': 'attention', 'severity_zone': 'B', 'related_dtcs': [], 'recommended_checks': ['Осмотреть ремень и натяжитель']}],
 'obd': {'mil_on': False, 'dtcs': [],
         'pids': [{'pid': 'J1939-190', 'name': 'engine_rpm', 'value': 1460, 'unit': 'rpm'},
                  {'pid': 'J1939-100', 'name': 'oil_pressure', 'value': 2.7, 'unit': 'bar'},
                  {'pid': 'J1939-157', 'name': 'rail_pressure', 'value': 352, 'unit': 'bar'}]},
 'recommended_checks': ['Проверить тепловые зазоры клапанов на холодном двигателе в плановое ТО', 'Контрольная запись после регулировки'],
 'service_hints': ['Лёгкое «тиканье» на всех цилиндрах, не зависит от температуры', 'Срочности нет: допущен к эксплуатации'],
 'disclaimer': DISCL}

# ───────────────────────────── S4 bad recording ─────────────────────────────
R['S4_bad_recording_uncertain'] = {
 'schema_version': '1.1.0',
 'meta': meta('S4', 'Плохая запись: низкий SNR, ветер, непрогретый двигатель → verdict=uncertain; агент не диагностирует, а просит повторную запись.'),
 'analysis': analysis('S4', '2026-11-18T16:52:41+07:00', 'driver_complaint'),
 'vehicle': vehicle('S4'),
 'recording': {
   'recorded_at': '2026-11-18T16:50:03+07:00', 'duration_s': 11, 'sample_rate_hz': 16000, 'channels': 1,
   'sensor_type': 'smartphone_mic', 'sensor_position': 'hood_open_near_valve_cover',
   'audio_ref': 'rec://demo/S4/LCV-NSK-0134/2026-11-18T16-50-03.wav',
   'conditions': {'engine_state': 'off_idle', 'engine_speed_rpm': 1200, 'engine_load_pct': None, 'coolant_temp_c': 52, 'oil_temp_c': 48,
                  'vehicle_speed_kph': 0, 'gear': 'N', 'ambient_temp_c': -9, 'environment': 'roadside'},
   'quality': {'status': 'rejected', 'snr_db': 6.1, 'rms_dbfs': -34.8, 'silence_ratio': 0.18, 'clipping_ratio': 0.031,
               'warnings': ['SNR 6,1 дБ ниже порога 15 дБ', 'Сильный ветер и шум дороги (запись у обочины)',
                            'Двигатель не прогрет (масло 48 °C, ОЖ 52 °C): условия записи не выполнены',
                            'Доля тишины 18 % при пороге 10 %', 'Клиппинг 3,1 % при пороге 1 %',
                            'Длительность 11 с при минимуме 20 с'],
               'rerecord_instructions': ['Прогреть двигатель до масла ≥ 80 °C и ОЖ ≥ 80 °C',
                                         'Записать в боксе или депо при закрытых дверях, без ветра и посторонних шумов',
                                         'Закрепить датчик на блоке под цилиндром 3 (магнит/шпилька), не держать телефон рукой',
                                         'Нейтраль, стояночный тормоз, 1 450 ± 100 об/мин, не менее 20 секунд (рекомендуется 25)']}},
 'overall': {'verdict': 'uncertain', 'anomaly_score': 0.44, 'severity': 'undetermined', 'severity_standard': STD,
             'urgency': 'recording_invalid', 'confidence': 0.12, 'requires_rerecord': True},
 'faults': [
   {'code': 'piston_slap', 'name_ru': 'Стук поршня', 'probability': 0.31, 'confidence': 0.08,
    'component': 'piston', 'location': {'bank': 1, 'cylinder': None, 'side': None},
    'frequency_bands': [{'f_low_hz': 1000, 'f_high_hz': 4000, 'peak_hz': 1800, 'amplitude': 4.0, 'unit': 'dB', 'shaft_order': 0.5}],
    'severity': 'undetermined', 'related_dtcs': [],
    'recommended_checks': ['Повторить запись по инструкции; результат не использовать для решений']},
   {'code': 'knock_detonation', 'name_ru': 'Жёсткое сгорание', 'probability': 0.22, 'confidence': 0.07,
    'component': 'combustion', 'location': {'bank': 1, 'cylinder': None, 'side': None},
    'frequency_bands': [{'f_low_hz': 1500, 'f_high_hz': 6000, 'peak_hz': 2200, 'amplitude': 3.2, 'unit': 'dB', 'shaft_order': 0.5}],
    'severity': 'undetermined', 'related_dtcs': [],
    'recommended_checks': ['Повторить запись по инструкции; результат не использовать для решений']}],
 'obd': {'mil_on': False, 'dtcs': [],
         'pids': [{'pid': 'J1939-190', 'name': 'engine_rpm', 'value': 1200, 'unit': 'rpm'},
                  {'pid': 'J1939-100', 'name': 'oil_pressure', 'value': 3.9, 'unit': 'bar'},
                  {'pid': 'J1939-110', 'name': 'coolant_temp', 'value': 52, 'unit': 'C'}]},
 'recommended_checks': ['Повторить запись: прогреть двигатель, писать в боксе, датчик на блоке, ≥ 20 с'],
 'service_hints': ['Запись непригодна для диагностики (rejected). Заключение по неисправности не выдаётся.'],
 'disclaimer': DISCL}

# ───────────────────────────── S5 conflicting ─────────────────────────────
R['S5_conflict_turbo_vs_intake_leak'] = {
 'schema_version': '1.1.0',
 'meta': meta('S5', 'Конфликт: ML → свист турбины (turbocharger_fault), но P0299 + история (хомут патрубка после ТО) указывают на утечку наддува.'),
 'analysis': analysis('S5', '2026-11-18T11:34:52+07:00', 'driver_complaint'),
 'vehicle': vehicle('S5'),
 'recording': {
   'recorded_at': '2026-11-18T11:30:17+07:00', 'duration_s': 24, 'sample_rate_hz': 25600, 'channels': 1,
   'sensor_type': 'combined', 'sensor_position': 'turbo_housing',
   'audio_ref': 'rec://demo/S5/LCV-NSK-0151/2026-11-18T11-30-17.wav',
   'conditions': {'engine_state': 'load', 'engine_speed_rpm': 2350, 'engine_load_pct': 70, 'coolant_temp_c': 91, 'oil_temp_c': 99,
                  'vehicle_speed_kph': 58, 'gear': '4', 'ambient_temp_c': -5, 'environment': 'open_road'},
   'quality': {'status': 'ok', 'snr_db': 16.4, 'rms_dbfs': -24.6, 'silence_ratio': 0.02, 'clipping_ratio': 0.004,
               'warnings': ['Запись на ходу под нагрузкой: допустима для проверки наддува, но не по схеме стр. 12-02 (нейтраль, без нагрузки)']}},
 'overall': {'verdict': 'anomaly', 'anomaly_score': 0.66, 'severity': 'warning', 'severity_zone': 'C', 'severity_standard': STD,
             'urgency': 'inspect_this_week', 'confidence': 0.6, 'requires_rerecord': False,
             'overall_vibration': {'rms_velocity_mm_s': 7.6, 'peak_acceleration_g': 3.1, 'frequency_range_hz': [2, 1000]}},
 'faults': [
   {'code': 'turbocharger_fault', 'name_ru': 'Неисправность турбокомпрессора (свист)', 'probability': 0.58, 'confidence': 0.6,
    'component': 'turbocharger', 'location': {'bank': 1, 'cylinder': None, 'side': None},
    'frequency_bands': [{'f_low_hz': 6000, 'f_high_hz': 16000, 'peak_hz': 9800, 'amplitude': 18.0, 'unit': 'dB', 'shaft_order': 1.0}],
    'severity': 'warning', 'severity_zone': 'C', 'related_dtcs': ['P0299'],
    'recommended_checks': ['Проверить осевой и радиальный люфт ротора турбокомпрессора', 'Проверить давление наддува и герметичность тракта наддува']},
   {'code': 'exhaust_leak', 'name_ru': 'Утечка в выпуске', 'probability': 0.14, 'confidence': 0.35,
    'component': 'exhaust_manifold', 'location': {'bank': 1, 'cylinder': None, 'side': None},
    'frequency_bands': [{'f_low_hz': 1000, 'f_high_hz': 5000, 'peak_hz': 2600, 'amplitude': 6.0, 'unit': 'dB', 'shaft_order': 2.0}],
    'severity': 'attention', 'severity_zone': 'B', 'related_dtcs': [],
    'recommended_checks': ['Осмотреть следы сажи у фланцев выпускного коллектора']},
   {'code': 'accessory_drive', 'name_ru': 'Привод навесного оборудования', 'probability': 0.08, 'confidence': 0.3,
    'component': 'accessory_belt', 'location': {'bank': None, 'cylinder': None, 'side': 'front'},
    'frequency_bands': [{'f_low_hz': 2000, 'f_high_hz': 6000, 'peak_hz': 2900, 'amplitude': 0.6, 'unit': 'g', 'shaft_order': None}],
    'severity': 'attention', 'severity_zone': 'B', 'related_dtcs': [], 'recommended_checks': ['Осмотреть ремень и натяжитель']}],
 'obd': {'mil_on': True,
   'dtcs': [{'code': 'P0299', 'status': 'active', 'system': 'engine', 'description': 'Недостаточный наддув'},
            {'code': 'P0101', 'status': 'pending', 'system': 'engine', 'description': 'Диапазон/производительность датчика расхода воздуха'}],
   'pids': [{'pid': 'J1939-190', 'name': 'engine_rpm', 'value': 2350, 'unit': 'rpm'},
            {'pid': 'J1939-100', 'name': 'oil_pressure', 'value': 3.1, 'unit': 'bar'},
            {'pid': None, 'name': 'boost_pressure_gauge', 'value': 0.55, 'unit': 'bar'}]},
 'recommended_checks': ['Проверить люфт ротора и герметичность тракта наддува', 'Сопоставить свист с кодом P0299 и историей обслуживания впускного тракта'],
 'service_hints': ['Свист на подъёме оборотов под нагрузкой, падение тяги', 'Классификатор не различает свист турбины и утечку наддува — нужна проверка на агрегате'],
 'disclaimer': DISCL}

if __name__ == '__main__':
    for k, v in R.items():
        dump(P('ml_responses', k + '.json'), v)
    print(len(R), 'ml files')
