import os

from idf_crowding.config import REPO_ROOT, deep_merge, find_upwards, load_config, load_env


def test_find_upwards_searches_parents(tmp_path):
    (tmp_path / ".env").write_text("X=1\n")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)

    assert find_upwards(".env", nested) == tmp_path / ".env"
    assert find_upwards("missing-file", nested) is None


def test_deep_merge_overrides_nested_keys():
    base = {"a": {"x": 1, "y": 2}, "b": 1}
    assert deep_merge(base, {"a": {"y": 3}}) == {"a": {"x": 1, "y": 3}, "b": 1}
    assert base["a"]["y"] == 2


def test_local_config_overrides_defaults(tmp_path):
    (tmp_path / "config.toml").write_text(
        '[paths]\nlive_dir = "data/live"\n[live.disruptions]\ninterval_seconds = 300\n'
    )
    (tmp_path / "config.local.toml").write_text("[live.disruptions]\ninterval_seconds = 120\n")

    config = load_config(tmp_path)

    assert config["live"]["disruptions"]["interval_seconds"] == 120
    assert config["paths"]["live_dir"] == str((tmp_path / "data/live").resolve())


def test_repo_config_loads():
    config = load_config(REPO_ROOT)
    assert config["live"]["disruptions"]["url"].startswith("https://")


def test_load_env_does_not_override_existing(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("IDF_TEST_VAR=from_file\n")
    monkeypatch.setenv("IDF_TEST_VAR", "from_env")

    assert load_env(tmp_path) == tmp_path / ".env"
    assert os.environ["IDF_TEST_VAR"] == "from_env"
