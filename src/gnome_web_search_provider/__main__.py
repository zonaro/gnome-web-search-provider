"""Allow running the provider with ``python -m gnome_web_search_provider``."""

from . import main

if __name__ == "__main__":
    raise SystemExit(main())