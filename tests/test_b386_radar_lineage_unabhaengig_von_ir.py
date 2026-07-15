"""B386: Die Radar-Lineage darf nicht an der IR-Pipeline hängen."""
import pytest


def _main_src():
    return open("main.py", encoding="utf-8").read()


def _indent_of(line):
    return len(line) - len(line.lstrip())


def test_radar_lineage_runs_before_ir_pipeline():
    """Der Lineage-Aufruf muss VOR run_ir_precursor_pipeline stehen."""
    src = _main_src()
    i_lineage = src.find("_radar_lineage_events = update_split_merge_lineage")
    i_ir = src.find('_ir_tracks = run_ir_precursor_pipeline(timestamp=timestamp, weather_data=weather_data, reason="radar_cycle")')
    assert i_lineage != -1, "Radar-Lineage-Aufruf nicht gefunden"
    assert i_ir != -1
    assert i_lineage < i_ir, "Radar-Lineage laeuft weiterhin nach der IR-Pipeline"


def test_radar_lineage_not_nested_in_ir_block():
    """Der Aufruf darf nicht mehr auf Einrueckungstiefe 25 liegen (IR-Pfad)."""
    for line in _main_src().splitlines():
        if "_radar_lineage_events = update_split_merge_lineage" in line:
            assert _indent_of(line) <= 17, (
                f"Aufruf liegt bei Einrueckung {_indent_of(line)} — weiterhin im IR-Block "
                "verschachtelt (war 25)"
            )
            return
    pytest.fail("Radar-Lineage-Aufruf nicht gefunden")


def test_only_one_lineage_call_remains():
    """Der alte, verschachtelte Aufruf muss entfernt sein."""
    src = _main_src()
    assert src.count("update_split_merge_lineage(") == 1, (
        "Es darf genau einen Aufruf geben — der verschachtelte ist zu entfernen"
    )


def test_dead_extend_removed():
    """`_lineage_events.extend(_split_merge_events)` war wirkungslos."""
    src = _main_src()
    assert "_lineage_events.extend(_split_merge_events" not in src
    assert "_split_merge_events" not in src


def test_radar_lineage_has_own_exception_handler():
    """Ein IR-Fehler darf die Radar-Lineage nicht mehr betreffen und umgekehrt."""
    src = _main_src()
    assert "_radar_lin_exc" in src, "Eigener Exception-Handler fehlt"
    assert "[B386] Radar-Split/Merge-Lineage fehlgeschlagen" in src


def test_pre_frame_snapshot_still_used():
    """B385 darf durch das Verschieben nicht verloren gehen."""
    src = _main_src()
    assert "last_previous_snapshot" in src
    assert "previous_objects=_prev_for_lineage" in src


def test_main_module_still_compiles():
    import py_compile
    py_compile.compile("main.py", doraise=True)
