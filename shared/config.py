"""
DonutNodes configuration management.

Loads settings from config.yaml in the donutnodes folder.
"""

import os
from pathlib import Path
from typing import Any, Optional

# Try to import yaml, fall back to basic parsing if not available
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

# Config file location
DONUTNODES_DIR = Path(__file__).parent.parent
CONFIG_FILE = DONUTNODES_DIR / "config.yaml"

# Default configuration
DEFAULT_CONFIG = {
    "civitai": {
        "api_key": "",
        "auto_lookup": True,
        "download_previews": True,
        "prefer_sfw": True,
        "cache_dir": "",
    }
}

# Cached config
_config: Optional[dict] = None


def _parse_yaml_simple(content: str) -> dict:
    """
    Simple YAML parser for basic key: value structures.
    Used as fallback when PyYAML is not installed.
    """
    config = {}
    current_section = None

    for line in content.split('\n'):
        line = line.rstrip()

        # Skip empty lines and comments
        if not line or line.strip().startswith('#'):
            continue

        # Check for section (no leading whitespace, ends with :)
        if not line.startswith(' ') and not line.startswith('\t') and line.endswith(':'):
            current_section = line[:-1].strip()
            config[current_section] = {}
            continue

        # Check for key: value
        if ':' in line:
            key, _, value = line.partition(':')
            key = key.strip()
            value = value.strip()

            # Parse value types
            if value == '""' or value == "''":
                value = ""
            elif value.lower() == 'true':
                value = True
            elif value.lower() == 'false':
                value = False
            elif value.isdigit():
                value = int(value)
            elif value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            elif value.startswith("'") and value.endswith("'"):
                value = value[1:-1]

            if current_section and current_section in config:
                config[current_section][key] = value
            else:
                config[key] = value

    return config


def load_config(force_reload: bool = False) -> dict:
    """
    Load configuration from config.yaml.

    Args:
        force_reload: If True, reload from disk even if cached

    Returns:
        Configuration dictionary
    """
    global _config

    if _config is not None and not force_reload:
        return _config

    # Start with defaults
    config = DEFAULT_CONFIG.copy()

    # Load from file if exists
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r') as f:
                content = f.read()

            if HAS_YAML:
                file_config = yaml.safe_load(content) or {}
            else:
                file_config = _parse_yaml_simple(content)

            # Merge with defaults (file values override defaults)
            for section, values in file_config.items():
                if section in config and isinstance(values, dict):
                    config[section].update(values)
                else:
                    config[section] = values

        except Exception as e:
            print(f"[DonutNodes] Error loading config: {e}")

    _config = config
    return config


def get_config(key: str, default: Any = None) -> Any:
    """
    Get a configuration value by dot-notation key.

    Args:
        key: Key in format "section.key" (e.g., "civitai.api_key")
        default: Default value if key not found

    Returns:
        Configuration value or default
    """
    config = load_config()

    parts = key.split('.')
    value = config

    for part in parts:
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return default

    return value


def get_civitai_api_key() -> str:
    """Get CivitAI API key from config."""
    return get_config("civitai.api_key", "") or ""


def get_civitai_auto_lookup() -> bool:
    """Get whether to auto-lookup LoRAs on CivitAI."""
    return get_config("civitai.auto_lookup", True)


def get_civitai_download_previews() -> bool:
    """Get whether to download preview images."""
    return get_config("civitai.download_previews", True)


def get_civitai_prefer_sfw() -> bool:
    """Get whether to prefer SFW preview images."""
    return get_config("civitai.prefer_sfw", True)


def get_civitai_cache_dir() -> Optional[str]:
    """Get custom cache directory, or None for default."""
    cache_dir = get_config("civitai.cache_dir", "")
    if cache_dir:
        # Handle relative paths
        if not os.path.isabs(cache_dir):
            cache_dir = str(DONUTNODES_DIR / cache_dir)
        return cache_dir
    return None


def save_config(config: dict) -> bool:
    """
    Save configuration to config.yaml.

    Args:
        config: Configuration dictionary to save

    Returns:
        True if saved successfully
    """
    global _config

    try:
        if HAS_YAML:
            content = yaml.dump(config, default_flow_style=False, sort_keys=False)
        else:
            # Simple YAML-like output
            lines = ["# DonutNodes Configuration\n"]
            for section, values in config.items():
                lines.append(f"\n{section}:")
                if isinstance(values, dict):
                    for key, value in values.items():
                        if isinstance(value, str):
                            value = f'"{value}"' if value else '""'
                        elif isinstance(value, bool):
                            value = str(value).lower()
                        lines.append(f"  {key}: {value}")
                else:
                    lines.append(f"  {values}")
            content = "\n".join(lines)

        with open(CONFIG_FILE, 'w') as f:
            f.write(content)

        _config = config
        return True

    except Exception as e:
        print(f"[DonutNodes] Error saving config: {e}")
        return False


# Load config on module import
load_config()
