import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
CI = (ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8")


def job(name: str) -> str:
    return re.search(rf"^{name}:\n(.*?)(?=^\S|\Z)", CI, re.M | re.S).group(1)


def test_no_unsafe_deploy_commands():
    assert "--force-recreate" not in CI
    assert not re.search(r"docker exec\s+-t\b", CI)
    for line in CI.splitlines():
        if "pg_dump" in line:
            assert not re.search(r"\|\|\s*(echo|true)\b", line)


@pytest.mark.parametrize("env", ["test", "prod"])
def test_backup_precedes_deploy(env):
    deploy = job(f"deploy-{env}")
    assert f"resource_group: deploy-{env}" in deploy
    assert "script:\n    - !reference [.disk-preflight, script]" in deploy
    assert "script:" in job(r"\.disk-preflight")
    assert deploy.index("pg_dump") < deploy.index("up -d --build --remove-orphans")
    assert '/data/db_backup/ux-architecture-' + env in deploy
    assert '"${SKIP_DB_BACKUP:-0}" = "1"' in deploy
    assert 'test -s "$file"' in deploy and 'rm -f "$file"' in deploy
    assert "exit 1" in deploy
    for stage in ("build", "deploy"):
        assert "after_script:\n    - rm -f .env" in job(f"{stage}-{env}")


@pytest.mark.parametrize("env,network", [("test", "cx-app_cx_net"), ("prod", "cx_copilot_cx_net")])
def test_external_network(env, network):
    compose = (ROOT / f"docker-compose.{env}.yaml").read_text(encoding="utf-8")
    assert f"    external: true\n    name: {network}\n" in compose
