from app.domain.mermaid import validate_mermaid


def test_accepts_flowchart_lr():
    assert validate_mermaid("flowchart LR\nA-->B").ok is True


def test_accepts_flowchart_tb():
    assert validate_mermaid("flowchart TB\nA-->B").ok is True


def test_accepts_td_bt_rl_directions():
    for direction in ("TD", "BT", "RL"):
        assert validate_mermaid(f"flowchart {direction}\nA-->B").ok is True, direction


def test_rejects_non_flowchart():
    assert validate_mermaid("graph LR\nA-->B").ok is False


def test_rejects_xss_content():
    result = validate_mermaid('flowchart LR\nA-->B["<script>alert(1)</script>"]')
    assert result.ok is False
