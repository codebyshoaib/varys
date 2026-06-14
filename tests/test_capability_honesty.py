import sys, os, sqlite3, tempfile, pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / ".claude" / "hooks"))

import varys_harness_db


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Give every test its own isolated SQLite DB."""
    db_path = tmp_path / "test_harness.db"
    monkeypatch.setattr(varys_harness_db, "HARNESS_DB", db_path)
    monkeypatch.setattr(varys_harness_db, "HARNESS_DIR", tmp_path)
    yield


from varys_harness_db import get_db, log_capability_gap, get_capability_gaps, update_gap_reaction


def test_log_and_read_gap():
    db = get_db()
    log_capability_gap(db, gap_type="inline_image", request_text="make infographic",
                       failed_step="nlm_query", fallback_used="text_summary")
    log_capability_gap(db, gap_type="inline_image", request_text="create image",
                       failed_step="upload", fallback_used="text_summary")
    gaps = get_capability_gaps(db, days=7)
    assert len(gaps) == 1
    assert gaps[0]["gap_type"] == "inline_image"
    assert gaps[0]["count"] == 2


def test_gap_reaction_update():
    db = get_db()
    log_capability_gap(db, gap_type="video_gen", request_text="make video",
                       failed_step="no_tool", fallback_used="none")
    update_gap_reaction(db, gap_type="video_gen", reaction="rejected")
    gaps = get_capability_gaps(db, days=7)
    video = next(g for g in gaps if g["gap_type"] == "video_gen")
    assert video["rejected_count"] >= 1


def test_extract_topic_from_text():
    sys.path.insert(0, str(Path(__file__).parent.parent / ".claude" / "hooks"))
    from infographic_handler import extract_topic
    assert extract_topic("create an infographic about pull-up progression") == "pull-up progression"
    assert extract_topic("make an infographic on swimming") == "swimming"
    assert extract_topic("infographic for cycling training zones") == "cycling training zones"


def test_detect_palette():
    sys.path.insert(0, str(Path(__file__).parent.parent / ".claude" / "hooks"))
    from infographic_handler import detect_palette
    assert detect_palette("pull-up progression calisthenics") == "fitness"
    assert detect_palette("Django REST API performance") == "tech"
    assert detect_palette("something random") == "tech"


def test_parse_nlm_points_numbered():
    sys.path.insert(0, str(Path(__file__).parent.parent / ".claude" / "hooks"))
    from infographic_handler import parse_nlm_points
    raw = "1. Keep your core tight\n2. Dead hang first\n3. Scapular pulls before full pull-ups"
    points = parse_nlm_points(raw)
    assert len(points) == 3
    assert points[0] == "Keep your core tight"


def test_parse_nlm_points_sentence_fallback():
    sys.path.insert(0, str(Path(__file__).parent.parent / ".claude" / "hooks"))
    from infographic_handler import parse_nlm_points
    raw = "Keep your core tight. Dead hang first. Scapular pulls are key."
    points = parse_nlm_points(raw)
    assert len(points) >= 1


def test_honesty_gate_passes_clean_response():
    sys.path.insert(0, str(Path(__file__).parent.parent / ".claude" / "hooks"))
    from honesty_gate import check
    result = check("Here's what I found about Django migrations.", uploaded=False,
                   request="tell me about migrations")
    assert result == "Here's what I found about Django migrations."


def test_honesty_gate_flags_false_claim_no_upload():
    sys.path.insert(0, str(Path(__file__).parent.parent / ".claude" / "hooks"))
    from honesty_gate import contains_delivery_claim
    assert contains_delivery_claim("Here it is! I posted the infographic.") is True
    assert contains_delivery_claim("Here's the image I made for you.") is True
    assert contains_delivery_claim("Here's what I know about pullups.") is False


def test_honesty_gate_passes_with_confirmed_upload():
    sys.path.insert(0, str(Path(__file__).parent.parent / ".claude" / "hooks"))
    from honesty_gate import check
    result = check("Here's the infographic you requested! 🤖 Varys", uploaded=True,
                   request="make infographic")
    assert "Here's the infographic" in result


def test_gap_watcher_promotion_logic():
    """get_capability_gaps() with min_count=2 returns gaps at threshold."""
    sys.path.insert(0, str(Path(__file__).parent.parent / ".claude" / "hooks"))
    import varys_harness_db as hdb
    db = hdb.get_db()
    hdb.log_capability_gap(db, gap_type="chart_rendering",
                           request_text="show me a chart", failed_step="no_tool",
                           fallback_used="none")
    hdb.log_capability_gap(db, gap_type="chart_rendering",
                           request_text="bar chart please", failed_step="no_tool",
                           fallback_used="none")
    gaps = hdb.get_capability_gaps(db, days=7, min_count=2)
    assert any(g["gap_type"] == "chart_rendering" for g in gaps)


def test_honesty_gate_rewrites_false_claim():
    """check() with a false claim and uploaded=False should return a different response."""
    import unittest.mock as mock
    sys.path.insert(0, str(Path(__file__).parent.parent / ".claude" / "hooks"))
    import honesty_gate

    fake_rewrite = "I wasn't able to upload that image. Try `nlm slides pullups` instead. 🤖 Varys"

    with mock.patch.object(honesty_gate, "_rewrite_honest", return_value=fake_rewrite):
        result = honesty_gate.check(
            draft="Here's the infographic you requested! 🤖 Varys",
            uploaded=False,
            request="make infographic about pullups",
        )

    assert result == fake_rewrite
    assert "Here's the infographic" not in result
