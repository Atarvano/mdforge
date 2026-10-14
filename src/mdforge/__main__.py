"""Allow ``python -m mdforge`` to behave like the ``mdforge`` console script."""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":  # pragma: no cover - module execution
    main()
