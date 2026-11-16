"""Configuration loading (config.json + optional environment overrides)."""
from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"


def _deep_merge(base: dict, override: dict) -> dict:
    out = deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (no extra dependency). Existing env vars win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def load_config(path: str | os.PathLike | None = None, overrides: dict | None = None) -> dict[str, Any]:
    """Load configuration from JSON and apply environment overrides.

    Supported environment variables (see .env.example):
      RENTSCRAPER_CONFIG          path to a config.json
      RENTSCRAPER_SOURCES         comma separated list of sources to enable
      RENTSCRAPER_OUTPUT_DIR      output directory
      RENTSCRAPER_HISTORY_FILE    history json path
      RENTSCRAPER_MIN_DELAY       minimum delay between requests to one host
      RENTSCRAPER_MAX_PAGES       cap on search pages per search (all sources)
      RENTSCRAPER_LOG_LEVEL       logging level (read by the CLI)
    """
    _load_dotenv(Path.cwd() / ".env")
    cfg_path = Path(path or os.environ.get("RENTSCRAPER_CONFIG") or DEFAULT_CONFIG_PATH)
    with open(cfg_path, encoding="utf-8") as fh:
        cfg = json.load(fh)

    env_sources = os.environ.get("RENTSCRAPER_SOURCES")
    if env_sources:
        wanted = {s.strip().lower() for s in env_sources.split(",") if s.strip()}
        for name, scfg in cfg.get("sources", {}).items():
            scfg["enabled"] = name in wanted

    if os.environ.get("RENTSCRAPER_OUTPUT_DIR"):
        cfg["output"]["directory"] = os.environ["RENTSCRAPER_OUTPUT_DIR"]
    if os.environ.get("RENTSCRAPER_HISTORY_FILE"):
        cfg["output"]["history_file"] = os.environ["RENTSCRAPER_HISTORY_FILE"]
    if os.environ.get("RENTSCRAPER_MIN_DELAY"):
        cfg["http"]["min_delay_seconds"] = float(os.environ["RENTSCRAPER_MIN_DELAY"])
    if os.environ.get("RENTSCRAPER_MAX_PAGES"):
        n = int(os.environ["RENTSCRAPER_MAX_PAGES"])
        for scfg in cfg.get("sources", {}).values():
            for key in ("max_pages", "max_pages_per_search"):
                if key in scfg:
                    scfg[key] = min(scfg[key], n)

    if overrides:
        cfg = _deep_merge(cfg, overrides)
    return cfg
