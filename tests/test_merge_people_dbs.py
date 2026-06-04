import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '.claude', 'hooks'))

def test_exact_match():
    from merge_people_dbs import match_people
    source = [{"name": "Mahnoor Baig", "slack_id": "U1"}]
    target = [{"notion_page_id": "p1", "name": "Mahnoor Baig", "slack_id": ""}]
    result = match_people(source, target)
    assert result[0]["match_type"] == "exact"
    assert result[0]["source"]["name"] == "Mahnoor Baig"

def test_fuzzy_match():
    from merge_people_dbs import match_people
    source = [{"name": "Mah Noor", "slack_id": "U2"}]
    target = [{"notion_page_id": "p2", "name": "Mahnoor", "slack_id": ""}]
    result = match_people(source, target)
    assert result[0]["match_type"] == "fuzzy"

def test_no_match_is_new():
    from merge_people_dbs import match_people
    source = [{"name": "Brand New Person", "slack_id": "U3"}]
    target = [{"notion_page_id": "p3", "name": "Totally Different", "slack_id": ""}]
    result = match_people(source, target)
    assert result[0]["match_type"] == "new"
