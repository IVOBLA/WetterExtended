"""B399: Metatests dürfen keine lokalen Variablennamen oder redundante IDs erzwingen."""

import ast
from pathlib import Path


def test_b384_does_not_require_old_m3_variable_name():
    src = Path("tests/test_b384_testsemantik_und_massstab.py").read_text(
        encoding="utf-8"
    )
    assert 'm3.get("lineage") == "merged"' not in src
    assert "ast.get_source_segment" in src


def test_b391_pending_emission_check_uses_mapping_key():
    src = Path(
        "tests/test_b391_merge_parent_ueberlebt_kandidatenphase.py"
    ).read_text(encoding="utf-8")

    tree = ast.parse(src)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "test_pending_parent_is_excluded_from_neighbor_features"
    )
    function_src = ast.get_source_segment(src, function) or ""

    assert "for track_id, value in mem_after_f2.items()" in function_src
    assert "pending_parent_id, pending_parent = pending[0]" in function_src
    assert 'pending_parent["id"]' not in function_src
