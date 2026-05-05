import glob, json

def migrate():
    m=a=u=0
    for p in glob.glob("train_data/objects/*.json"):
        try:
            data=json.load(open(p,encoding="utf-8")); changed=False
            for o in data:
                for k,v in {"lineage":"new","parents":[],"children":[],"lineage_end":None}.items():
                    if k not in o: o[k]=v; changed=True
            if changed:
                json.dump(data,open(p,"w",encoding="utf-8"),indent=2); m+=1
            else: a+=1
        except Exception:
            u+=1
    print(f"{m} Dateien migriert, {a} Dateien bereits aktuell, {u} Dateien nicht lesbar")

if __name__=="__main__": migrate()
