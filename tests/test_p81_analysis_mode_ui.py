"""P81: Admin-Karten fuer Betriebsart und lokale Analyse, plus Handbuch."""
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[1]
PAGE = REPO_ROOT / "frontend" / "src" / "pages" / "AiSuggestions.jsx"
HANDBUCH = REPO_ROOT / "docs" / "WetterExtended_Benutzerhandbuch.md"
def _page(): return PAGE.read_text(encoding="utf-8")
def _handbuch(): return HANDBUCH.read_text(encoding="utf-8")
def test_mode_card_exists(): assert "Betriebsart der täglichen Analyse" in _page()
def test_mode_card_offers_exactly_two_options():
 t=_page(); assert "value: 'repo'" in t and "value: 'local'" in t
def test_mode_card_uses_radio_not_two_toggles():
 block=_page().split("Betriebsart der täglichen Analyse",1)[1].split("</div>\n\n\n",1)[0]; assert 'type="radio"' in block; assert 'name="analysis_mode"' in block
def test_mode_card_states_the_once_per_day_rule(): assert "genau eine" in _page().lower()
def test_mode_is_saved_through_its_own_endpoint():
 t=_page(); assert "api.post('/api/analysis_mode', { mode: next })" in t; assert "api.get('/api/analysis_mode')" in t
def test_local_mode_warns_about_the_external_routine():
 t=_page(); assert "Externe Routine jetzt abschalten" in t; assert "zwei Analysen pro Tag" in t
def test_switch_day_is_explained():
 t=_page(); assert "changed_today" in t; assert "morgen" in t
def test_local_card_exists(): assert "Lokale Analyse am Pi (Claude Code)" in _page()
def test_local_card_has_no_second_enable_toggle():
 block=_page().split("Lokale Analyse am Pi (Claude Code)",1)[1]; assert "laCfg.enabled" not in block; assert "Lokale Analyse aktiviert" not in block
def test_local_card_shows_whether_it_is_active(): assert "mode.mode === 'local'" in _page()
def test_all_configurable_fields_are_editable():
 t=_page()
 for field in ("max_turns","timeout_s"): assert f"laCfg.{field}" in t
def test_numeric_inputs_have_bounds_matching_the_api():
 block=_page().split("Lokale Analyse am Pi (Claude Code)",1)[1]
 for bound in ('max="500"','max="3600"'): assert bound in block
def test_manual_run_uses_the_existing_job_route():
 t=_page(); assert "api.post('/api/system/run_job/local_analysis', {})" in t; assert "/api/local_analysis/run" not in t
def test_manual_run_polls_and_gives_up_eventually():
 block=_page().split("async function runLocalAnalysis",1)[1].split("\n  }\n",1)[0]; assert "job_status" in block; assert "clearInterval" in block; assert "ticks" in block
def test_run_button_is_disabled_while_running(): assert "disabled={laRunning}" in _page()
def test_missing_cli_is_surfaced_to_the_user():
 t=_page(); assert "cli_available" in t; assert "claude.ai/install.sh" in t
def test_handbuch_documents_the_mode(): assert "Betriebsart der täglichen Analyse" in _handbuch()
def _chapter(): return _handbuch().split("### Betriebsart der täglichen Analyse",1)[1]
def test_handbuch_states_the_once_per_day_rule(): assert "genau einmal pro Tag" in _chapter()
def test_handbuch_tells_the_user_to_disable_the_external_run(): assert "von Hand abzuschalten" in _chapter()
def test_handbuch_explains_the_switch_day(): assert "Folgetag" in _chapter()
def test_handbuch_mentions_read_only_nature(): assert "lesend" in _chapter()
def test_handbuch_has_no_bugfix_wording():
 t=_chapter().lower()
 for bad in ("bugfix","fehlerbehebung","regression"): assert bad not in t
