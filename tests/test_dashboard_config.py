from src import dashboard_config


def test_get_host_defaults_to_localhost(monkeypatch):
    monkeypatch.delenv("DASHBOARD_HOST", raising=False)
    assert dashboard_config.get_host() == "127.0.0.1"


def test_get_host_reads_env_var(monkeypatch):
    monkeypatch.setenv("DASHBOARD_HOST", "192.168.1.23")
    assert dashboard_config.get_host() == "192.168.1.23"


def test_get_port_defaults_to_8765(monkeypatch):
    monkeypatch.delenv("DASHBOARD_PORT", raising=False)
    assert dashboard_config.get_port() == 8765


def test_get_port_reads_env_var(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PORT", "9000")
    assert dashboard_config.get_port() == 9000


def test_get_port_falls_back_on_malformed_value(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PORT", "not-a-number")
    assert dashboard_config.get_port() == 8765


def test_dashboard_url_none_while_still_localhost(monkeypatch):
    monkeypatch.delenv("DASHBOARD_HOST", raising=False)
    assert dashboard_config.dashboard_url() is None


def test_dashboard_url_built_once_host_is_set(monkeypatch, tmp_path):
    monkeypatch.setattr(dashboard_config, "TOKEN_PATH", tmp_path / "dashboard_token.txt")
    monkeypatch.setenv("DASHBOARD_HOST", "192.168.1.23")
    monkeypatch.setenv("DASHBOARD_PORT", "9000")
    monkeypatch.setenv("DASHBOARD_TOKEN", "tok")
    assert dashboard_config.dashboard_url() == "http://192.168.1.23:9000/?token=tok"
