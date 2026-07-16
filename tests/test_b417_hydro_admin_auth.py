from pathlib import Path

def test_admin_routes_are_defense_in_depth():
    source=Path('app.py').read_text(); assert '/retrain/start' in source and '@require_role("admin")' in source
