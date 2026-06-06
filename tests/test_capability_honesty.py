import sys, os, sqlite3, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / ".claude" / "hooks"))

# Patch HARNESS_DB to a temp file before importing
import kamil_harness_db
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
kamil_harness_db.HARNESS_DB = Path(_tmp.name)
kamil_harness_db.HARNESS_DIR = Path(_tmp.name).parent

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
