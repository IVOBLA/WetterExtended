"""P77: Tests des lokalen Analyse-Runners; die CLI wird nie aufgerufen."""
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest

ROOT=Path(__file__).resolve().parents[1]
TOOL=ROOT/'tools/run_local_analysis.py'
SETTINGS=ROOT/'tools/local_analysis_settings.json'
PROMPT=ROOT/'docs/LOCAL_ANALYSIS_PROMPT.md'
TZ=ZoneInfo('Europe/Vienna')

@pytest.fixture
def runner(monkeypatch):
 spec=importlib.util.spec_from_file_location('run_local_analysis_p77',TOOL); mod=importlib.util.module_from_spec(spec); monkeypatch.setitem(sys.modules,spec.name,mod); spec.loader.exec_module(mod); return mod

def test_companions(): assert TOOL.is_file() and SETTINGS.is_file() and PROMPT.is_file()
def test_settings():
 deny=json.loads(SETTINGS.read_text())['permissions']['deny']; joined=' '.join(deny)
 for item in ('Bash(git push *)','Bash(sudo *)','Bash(rm *)','Read(./.env)'): assert item in deny
 assert '.env' in joined
 # B468: blosse Werkzeugnamen brechen den Lauf ab ('matches no known tool')
 assert all('(' in r and r.endswith(')') for r in deny), [r for r in deny if '(' not in r]
def test_prompt():
 text=PROMPT.read_text(); assert 'code_ref=' in text and 'beleg=' in text and 'zusammenfassung' in text and 'AIChecks.md' in text
def test_default_allowlist(runner):
 import config; runner.validate_allowed_tools(config.LOCAL_ANALYSIS_CONFIG['allowed_tools'])
@pytest.mark.parametrize('spec',['Read,Write','Read,Edit','Read,Bash(git push origin main)','Read,Bash(sudo x)','Read,Bash(rm -rf x)','Read,Bash(pip install x)','Read,Bash(python3 -c x)'])
def test_writes_rejected(runner,spec):
 with pytest.raises(runner.PreconditionError): runner.validate_allowed_tools(spec)
@pytest.mark.parametrize('spec',['Read,Bash(cat *)','Read,Bash(head *)','Read,Bash(tail *)'])
def test_bypass_rejected(runner,spec):
 with pytest.raises(runner.PreconditionError): runner.validate_allowed_tools(spec)
@pytest.mark.parametrize('spec',['Read,Bash(sqlite3 *)','Read,Bash(sqlite3 -readonly *)','Read,Bash(journalctl *)','Read,Bash(systemctl status *)','Read,Bash(ls *)','Read,Bash(python3 tools/ro_query.py *),Bash(rm *)'])
def test_wildcard_shell_rules_rejected(runner,spec):
 with pytest.raises(runner.PreconditionError): runner.validate_allowed_tools(spec)
def test_read_required(runner):
 with pytest.raises(runner.PreconditionError): runner.validate_allowed_tools('Grep,Glob')
def test_split_respects_parentheses(runner):
 assert runner.split_allowed_tools('Read,Grep,Bash(python3 tools/ro_query.py *)')==['Read','Grep','Bash(python3 tools/ro_query.py *)']
def test_empty_rejected(runner):
 with pytest.raises(runner.PreconditionError): runner.validate_allowed_tools(' ')
def test_env(runner):
 env=runner.build_subprocess_env({'PATH':'/b','HOME':'/h','GITHUB_TOKEN':'x','JWT_SECRET':'x','FOO':'x'}); assert env['PATH']=='/b' and env['DISABLE_AUTOUPDATER']=='1' and 'FOO' not in env and not any('TOKEN' in x or 'SECRET' in x for x in env)
@pytest.mark.parametrize('mode,changed,status,hour,expected',[('repo','',{},3,'mode_repo'),('x','',{},3,'mode_repo'),('local','2026-07-24',{},3,'mode_changed_today'),('local','',{},0,'not_due_yet'),('local','',{'last_success_date':'2026-07-24'},3,'already_ran_today'),('local','',{'last_attempt_date':'2026-07-24','attempts_today':3},3,'max_attempts_reached'),('local','',{},3,'due')])
def test_due(runner,mode,changed,status,hour,expected):
 due,reason=runner.is_due(mode,changed,{'cron_hour':0,'cron_minute':10},status,datetime(2026,7,24,hour,5,tzinfo=TZ)); assert reason==expected and due==(expected=='due')
def answer(inner,**kw):
 body=json.dumps(inner); body='```json\n'+body+'\n```' if kw.pop('fenced',False) else body; return json.dumps({'is_error':False,'result':body,**kw})
def test_extract(runner): assert runner.extract_payload(answer({'zusammenfassung':' ok '}))['zusammenfassung']=='ok'
def test_fenced(runner): assert runner.extract_payload(answer({'zusammenfassung':'ok','fehler':['x']},fenced=True))['fehler']==['x']
@pytest.mark.parametrize('raw',[json.dumps({'is_error':True,'result':'x'}),answer({'fehler':[]}),answer({'zusammenfassung':'x','fehler':'no'}),'garbage'])
def test_bad_payload(runner,raw):
 with pytest.raises(ValueError): runner.extract_payload(raw)
def test_command(runner,tmp_path):
 cmd=runner.build_command({'allowed_tools':'Read','max_turns':7,'model':''},'/claude','A',tmp_path/'s'); assert cmd[:3]==['/claude','-p','A'] and cmd[cmd.index('--permission-mode')+1]=='dontAsk' and '--dangerously-skip-permissions' not in cmd and '--model' not in cmd
def test_model(runner,tmp_path): assert runner.build_command({'allowed_tools':'Read','model':'m'},'/c','A',tmp_path/'s')[-2:]==['--model','m']
def test_atomic(runner,tmp_path):
 path=tmp_path/'x/a.json'; runner.write_json_atomic(path,{'a':1}); assert json.loads(path.read_text())=={'a':1} and not list(tmp_path.rglob('*.tmp'))
def test_repo_mode_no_cli(runner,tmp_path,monkeypatch):
 monkeypatch.setattr(runner,'load_mode',lambda _:('repo','')); monkeypatch.setattr(runner,'load_config',lambda _:{'status_path':'status.json'}); monkeypatch.setattr(runner.subprocess,'run',lambda *a,**k: pytest.fail('CLI called')); assert runner.main(['--repo-dir',str(tmp_path)])==0; assert json.loads((tmp_path/'status.json').read_text())['state']=='mode_repo'
def test_missing_prompt(runner,tmp_path,monkeypatch):
 monkeypatch.setattr(runner,'resolve_claude_bin',lambda _:'/c'); monkeypatch.setattr(runner,'load_mode',lambda _:('local','')); monkeypatch.setattr(runner,'load_config',lambda _:{'allowed_tools':'Read','prompt_path':'missing','status_path':'status.json'}); assert runner.main(['--repo-dir',str(tmp_path),'--force'])==1

def test_next_day_runs(runner):
 due,_=runner.is_due('local','2026-07-23',{'cron_hour':0,'cron_minute':10},{'last_success_date':'2026-07-23'},datetime(2026,7,24,3,tzinfo=TZ)); assert due

def test_environment_defaults(runner):
 env=runner.build_subprocess_env({}); assert env['PATH'] and env['HOME'] and env['DISABLE_AUTOUPDATER']=='1'

def test_null_lists_are_normalized(runner):
 out=runner.validate_payload({'zusammenfassung':'ok','fehler':None}); assert out['fehler']==[] and out['prompts']==[]
