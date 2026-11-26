"""Пересборка всего датасета: python3 tools/build_all.py (из папки agent_data)."""
import subprocess, sys, os
here = os.path.dirname(os.path.abspath(__file__))
for s in ['build_schema.py', 'build_ml.py', 'build_cards_history.py', 'build_dialogs_requests.py', 'build_golden.py', 'validate.py']:
    print('>>', s); r = subprocess.run([sys.executable, os.path.join(here, s)], cwd=here)
    if r.returncode: sys.exit(r.returncode)
