import sys, os, sqlite3, tempfile, pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / ".claude" / "hooks"))

import kamil_harness_db


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Give every test its own isolated SQLite DB."""
    db_path = tmp_path / "test_harness.db"
    monkeypatch.setattr(kamil_harness_db, "HARNESS_DB", db_path)
    monkeypatch.setattr(kamil_harness_db, "HARNESS_DIR", tmp_path)
    yield


from kamil_harness_db import get_db, log_capability_gap, get_capability_gaps, update_gap_reaction


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
    assert contains_delivery_claim("I've sent you the image.") is True
    assert contains_delivery_claim("Here's what I know about pullups.") is False


def test_honesty_gate_passes_with_confirmed_upload():
    sys.path.insert(0, str(Path(__file__).parent.parent / ".claude" / "hooks"))
    from honesty_gate import check
    result = check("Here it is — your infographic! 🤖 Kamil", uploaded=True,
                   request="make infographic")
    assert "Here it is" in result
