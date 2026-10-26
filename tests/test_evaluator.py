"""Unit tests for benchmark metrics calculation (Precision, Recall, F1, and root cause accuracy)."""

from core.schemas import Finding
from benchmarks.evaluate import score_findings, score_incident_root_cause


def test_score_findings_perfect_match():
    """Verify precision, recall, and F1 return 1.0 on exact ground truth match."""
    reported = [
        Finding(category="bug", title="Off-by-one boundary defect", description="In cart.py"),
        Finding(category="security", title="SQL injection vulnerability", description="In db.py"),
    ]
    gt = [
        {"category": "bug", "title_keywords": ["off-by-one", "boundary"]},
        {"category": "security", "title_keywords": ["sql injection"]},
    ]

    prec, rec, f1 = score_findings(reported, gt)
    assert prec == 1.0
    assert rec == 1.0
    assert f1 == 1.0


def test_score_findings_partial_match():
    """Verify metrics with false positives and false negatives."""
    reported = [
        Finding(category="bug", title="Off-by-one error", description="True positive"),
        Finding(category="general", title="Spurious note", description="False positive"),
    ]
    gt = [
        {"category": "bug", "title_keywords": ["off-by-one"]},
        {"category": "security", "title_keywords": ["sql injection"]},  # False negative
    ]

    prec, rec, f1 = score_findings(reported, gt)
    # 1 TP out of 2 reported => Precision = 0.5
    # 1 TP out of 2 ground truth => Recall = 0.5
    # F1 = 0.5
    assert prec == 0.5
    assert rec == 0.5
    assert f1 == 0.5


def test_score_incident_root_cause():
    """Verify root cause matching on keyword triggers."""
    reported = [
        Finding(category="incident", title="Connection pool exhaustion cascade", description="DB connection pool died")
    ]
    gt_root = {"trigger_keywords": ["connection pool", "exhaustion"]}

    assert score_incident_root_cause(reported, gt_root)

    unrelated = [
        Finding(category="incident", title="CSS render glitch", description="Browser layout issue")
    ]
    assert not score_incident_root_cause(unrelated, gt_root)
