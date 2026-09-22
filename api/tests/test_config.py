from pathlib import Path

from app.config import Settings


def test_env_files_are_independent_of_working_directory(tmp_path, monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    root_env = tmp_path / ".env"
    api_env = tmp_path / "api" / ".env"
    api_env.parent.mkdir()
    root_env.write_text("CORS_ORIGINS=http://localhost:3000\n", encoding="utf-8")
    monkeypatch.setitem(Settings.model_config, "env_file", (root_env, api_env))
    monkeypatch.chdir(api_env.parent)
    assert Settings().cors_origins == ["http://localhost:3000"]
    api_env.write_text("CORS_ORIGINS=http://localhost:3001\n", encoding="utf-8")
    assert Settings().cors_origins == ["http://localhost:3001"]
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3002")
    assert Settings().cors_origins == ["http://localhost:3002"]


def test_default_env_paths_point_to_repository_and_api():
    root = Path(__file__).resolve().parents[2]
    assert Settings.model_config["env_file"] == (root / ".env", root / "api" / ".env")
