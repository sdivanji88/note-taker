import pytest
import uvicorn

from note_taker import __main__ as cli


@pytest.fixture
def captured(monkeypatch):
    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(app=app, **kw))
    return seen


def _args(tmp_path, *extra):
    return ["--port", "8765", "--data-dir", str(tmp_path / "d"), *extra]


def test_token_from_env_only(tmp_path, monkeypatch, captured):
    monkeypatch.setenv("NOTE_TAKER_TOKEN", "from-env")
    cli.main(_args(tmp_path))
    assert captured["app"].state.config.token == "from-env"


def test_token_from_argv_only(tmp_path, monkeypatch, captured):
    monkeypatch.delenv("NOTE_TAKER_TOKEN", raising=False)
    cli.main(_args(tmp_path, "--token", "from-argv"))
    assert captured["app"].state.config.token == "from-argv"


def test_env_wins_over_argv(tmp_path, monkeypatch, captured):
    monkeypatch.setenv("NOTE_TAKER_TOKEN", "from-env")
    cli.main(_args(tmp_path, "--token", "from-argv"))
    assert captured["app"].state.config.token == "from-env"


def test_missing_token_exits_with_clear_message(tmp_path, monkeypatch, captured, capsys):
    monkeypatch.delenv("NOTE_TAKER_TOKEN", raising=False)
    with pytest.raises(SystemExit) as exc:
        cli.main(_args(tmp_path))
    assert exc.value.code != 0
    assert "NOTE_TAKER_TOKEN" in capsys.readouterr().err
    assert "app" not in captured
