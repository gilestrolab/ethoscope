"""Single source of truth for resolving the node's bootstrap paths.

The configuration directory is a *bootstrap* parameter: it must be known before
the configuration file itself can be read, so it cannot be stored inside that
file. It is resolved, in priority order, from:

1. an explicit argument / CLI flag,
2. the ``ETHOSCOPE_CONFIG_DIR`` environment variable,
3. ``{ETHOSCOPE_DATA_DIR}/config`` (default data dir: ``/ethoscope_data``).

A tiny **bootstrap environment file** at a fixed, well-known path
(:data:`BOOTSTRAP_ENV_FILE`) holds ``ETHOSCOPE_DATA_DIR`` / ``ETHOSCOPE_CONFIG_DIR``
so the choice survives restarts and is shared by every service (systemd units
load it via ``EnvironmentFile=``; bash scripts ``source`` it; Python reads the
resulting environment variables). The env file is the *only* thing kept at the
fixed path — all actual config content lives under the resolved config dir.

This module has no dependencies on the rest of ``ethoscope_node`` so it can be
imported from anywhere (including very early during startup) without import
cycles.
"""

import os
import shutil

DEFAULT_DATA_DIR = "/ethoscope_data"

# Fixed bootstrap anchor. Holds only pointers (ETHOSCOPE_DATA_DIR /
# ETHOSCOPE_CONFIG_DIR), never config content. Must NOT live inside the
# configurable config dir, otherwise resolving the config dir would be circular.
BOOTSTRAP_ENV_FILE = "/etc/ethoscope/environment"


def resolve_data_dir(explicit: str | None = None) -> str:
    """Resolve the root data directory.

    Args:
        explicit: An explicitly provided path (CLI flag/argument). Wins if set.

    Returns:
        The data directory: ``explicit`` → ``$ETHOSCOPE_DATA_DIR`` → default.
    """
    return explicit or os.environ.get("ETHOSCOPE_DATA_DIR") or DEFAULT_DATA_DIR


def resolve_config_dir(explicit: str | None = None, data_dir: str | None = None) -> str:
    """Resolve the configuration directory.

    Args:
        explicit: An explicitly provided config dir (CLI flag/argument). Wins if set.
        data_dir: Optional data dir used to derive the default ``{data_dir}/config``.

    Returns:
        The config directory: ``explicit`` → ``$ETHOSCOPE_CONFIG_DIR`` →
        ``{resolve_data_dir(data_dir)}/config``.
    """
    if explicit:
        return explicit
    env_config_dir = os.environ.get("ETHOSCOPE_CONFIG_DIR")
    if env_config_dir:
        return env_config_dir
    return os.path.join(resolve_data_dir(data_dir), "config")


def write_bootstrap_env(
    data_dir: str, config_dir: str, env_file: str = BOOTSTRAP_ENV_FILE
) -> None:
    """Persist the resolved paths to the bootstrap environment file.

    This is what makes a wizard-chosen location durable: systemd units load this
    file, so the next start of every node service picks up the new paths.

    Args:
        data_dir: Root data directory to record.
        config_dir: Configuration directory to record.
        env_file: Target env file (defaults to the fixed bootstrap path).

    Raises:
        OSError: If the file (or its parent directory) cannot be written.
    """
    os.makedirs(os.path.dirname(env_file), exist_ok=True)
    with open(env_file, "w", encoding="utf-8") as f:
        f.write("# Ethoscope node bootstrap environment. Auto-generated.\n")
        f.write("# Pointers only — actual config content lives under the config dir.\n")
        f.write(f"ETHOSCOPE_DATA_DIR={data_dir}\n")
        f.write(f"ETHOSCOPE_CONFIG_DIR={config_dir}\n")


def migrate_config_dir(
    old_dir: str, new_dir: str, exclude: set[str] | None = None
) -> list[str]:
    """Move existing config content from ``old_dir`` into ``new_dir``.

    Idempotent and non-destructive: entries that already exist at the destination
    are left untouched (never overwritten), so re-running is safe. The bootstrap
    env file is excluded by default because it must stay at its fixed path.

    Args:
        old_dir: Source config directory.
        new_dir: Destination config directory.
        exclude: Entry names to skip. Defaults to the files that are pinned to a
            fixed path by a systemd unit's ``EnvironmentFile=`` and therefore must
            not move: the bootstrap ``environment`` file and the tunnel's
            ``tunnel.env``.

    Returns:
        The list of entry names actually moved (empty if nothing to do).
    """
    if exclude is None:
        exclude = {"environment", "tunnel.env"}

    moved: list[str] = []
    if not old_dir or not new_dir:
        return moved
    if os.path.abspath(old_dir) == os.path.abspath(new_dir):
        return moved
    if not os.path.isdir(old_dir):
        return moved

    os.makedirs(new_dir, exist_ok=True)
    for name in os.listdir(old_dir):
        if name in exclude:
            continue
        src = os.path.join(old_dir, name)
        dst = os.path.join(new_dir, name)
        # Never overwrite something already present at the destination.
        if os.path.exists(dst):
            continue
        shutil.move(src, dst)
        moved.append(name)
    return moved
