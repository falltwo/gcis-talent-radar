"""Verify the shipped campus snapshot without changing the database."""
from scripts.verify_campus_delivery import verify


def test_delivery_accepts_history_with_one_active_snapshot():
    result = verify()
    assert result['read_only'] is True
    assert result['integrity'] == 'ok'
    assert result['campuses'] == 22
