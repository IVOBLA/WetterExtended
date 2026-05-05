import base64, glob, io, json, os, subprocess
from datetime import datetime
from pathlib import Path
from flask import Flask, jsonify, render_template, request
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

app = Flask(__name__)
ROOT=Path('.')


def _git_info():
    try: b=subprocess.check_output(['git','rev-parse','--abbrev-ref','HEAD'],text=True).strip()
    except Exception: b='unknown'
    try: c=subprocess.check_output(['git','rev-parse','--short','HEAD'],text=True).strip()
    except Exception: c='unknown'
    return b,c

def _latest_objects():
    files=sorted(glob.glob('train_data/objects/*.json'))
    if not files: return []
    with open(files[-1],encoding='utf-8') as f: return json.load(f)

@app.route('/')
def index():
    branch,commit=_git_info(); versions=sorted(glob.glob('train_data/models/v_*'))
    latest_meta=None
    metas=sorted(glob.glob('train_data/models/v_*/training_meta.json'))
    if metas:
        latest_meta=json.load(open(metas[-1],encoding='utf-8'))
    return render_template('dashboard.html', obj_count=len(_latest_objects()), latest_meta=latest_meta, versions=len(versions), branch=branch, commit=commit)

@app.route('/map')
def map_view(): return render_template('map.html')

@app.route('/logs')
def logs():
    def tail(unit):
        try:return subprocess.check_output(['journalctl','-u',unit,'-n','500','--no-pager'],text=True)
        except Exception as e:return f'Fehler: {e}'
    return render_template('logs.html', logs_a=tail('wetterprojekt'), logs_b=tail('wetterprojekt-scheduler'))

@app.route('/config', methods=['GET','POST'])
def config_view():
    import config
    cfg={k:getattr(config,k) for k in dir(config) if k.startswith(('ML_','RETRAIN_','DATASET_','LIVE_'))}
    banner=None
    if request.method=='POST':
        Path('train_data').mkdir(exist_ok=True)
        overrides=request.form.to_dict()
        json.dump(overrides, open('train_data/runtime_overrides.json','w',encoding='utf-8'), indent=2)
        banner='Änderungen wirken erst nach Service-Neustart und nur, wenn Overrides in der Pipeline aktiviert wurden.'
    return render_template('config.html', cfg=cfg, banner=banner)

@app.route('/progress')
def progress():
    rows=[]
    for p in sorted(glob.glob('train_data/models/v_*/training_meta.json')):
        m=json.load(open(p,encoding='utf-8')); rows.append(m)
    vers=list(range(1,len(rows)+1)); vl=[r.get('lstm',{}).get('val_loss') for r in rows]
    h10=[r.get('evaluation',{}).get('mae_by_horizon',{}).get('10') for r in rows]; h20=[r.get('evaluation',{}).get('mae_by_horizon',{}).get('20') for r in rows]; h30=[r.get('evaluation',{}).get('mae_by_horizon',{}).get('30') for r in rows]
    auc=[r.get('intensification',{}).get('auc') for r in rows]
    def mk(title, series):
        fig,ax=plt.subplots();
        for y,label in series: ax.plot(vers,y,label=label)
        ax.set_title(title); ax.legend(); buf=io.BytesIO(); fig.savefig(buf,format='png'); plt.close(fig); return base64.b64encode(buf.getvalue()).decode('utf-8')
    return render_template('progress.html', p1=mk('val_loss',[(vl,'val_loss')]), p2=mk('mae_by_horizon',[(h10,'h10'),(h20,'h20'),(h30,'h30')]), p3=mk('Intensification AUC',[(auc,'auc')]), rows=rows)

@app.route('/api/objects')
def api_objects(): return jsonify(_latest_objects())

@app.route('/api/forecast')
def api_forecast():
    feats=[]
    for o in _latest_objects():
        if 'forecast_lat_30' in o and 'forecast_lon_30' in o and 'lat' in o and 'lon' in o:
            feats.append({'type':'Feature','geometry':{'type':'LineString','coordinates':[[o['lon'],o['lat']],[o['forecast_lon_30'],o['forecast_lat_30']]]},'properties':{'id':o.get('id')}})
    return jsonify({'type':'FeatureCollection','features':feats})

if __name__=='__main__':
    app.run(host='0.0.0.0', port=5000, debug=os.getenv('ADMIN_DEBUG')=='1')
