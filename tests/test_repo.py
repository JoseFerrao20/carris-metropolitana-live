from cmlive.db.repo import build_legacy_map


def test_legacy_map_bare_and_prefixed_and_ambiguous():
    rows = [
        ("330037", "030037"),
        ("100001", "LA77N-100001|BNA17-100001"),
        ("X1", "999"),
        ("X2", "999"),  # ambíguo: ignorado
        ("Y", None),
    ]
    m = build_legacy_map(rows)
    assert m["030037"] == "330037"
    assert m["LA77N-100001"] == "100001" and m["100001"] == "100001"
    assert "999" not in m
