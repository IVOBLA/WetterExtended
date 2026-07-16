import hydro_flood_ml as h

def test_readiness_uses_shared_analysis(monkeypatch):
    rows=[]
    monkeypatch.setattr(h,"migrate_productive_dataset",lambda:{})
    monkeypatch.setattr(h,"load_trainable_labeled_samples",lambda *_:rows)
    status=h.readiness_status(); analysis=h.analyze_training_dataset(rows)
    assert status["event_count"]==analysis["event_count"]
    assert "insufficient_independent_events" in status["rejection_reasons"]
