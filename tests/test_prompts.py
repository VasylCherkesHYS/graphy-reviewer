from app.review.prompts import build_review_prompt


def test_semantic_section_included_when_present():
    prompt = build_review_prompt("diff", "graph ctx", "RELATED CODE HERE", 1000)
    assert "SEMANTICALLY RELATED CODE" in prompt
    assert "RELATED CODE HERE" in prompt
    assert "GRAPH CONTEXT" in prompt


def test_semantic_section_omitted_when_empty():
    prompt = build_review_prompt("diff", "graph ctx", "", 1000)
    assert "SEMANTICALLY RELATED CODE" not in prompt


def test_diff_truncation():
    prompt = build_review_prompt("X" * 50, "g", "", 10)
    assert "diff truncated at 10 chars" in prompt
