"""CLI: načte config.yaml, vygeneruje rozpis a vypíše ho na stdout."""

from __future__ import annotations

import sys
from pathlib import Path

from .config import load_config
from .core import NelzeSestavitError, generate_schedule

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config.yaml"


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    cesta_konfigu = Path(argv[0]) if argv else DEFAULT_CONFIG

    config = load_config(cesta_konfigu)

    try:
        schedule = generate_schedule(config)
    except NelzeSestavitError as e:
        print(e)
        return 1

    print(schedule.to_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
