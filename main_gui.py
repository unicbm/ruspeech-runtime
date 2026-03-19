"""GUI entry point for the local speech runtime."""

from __future__ import annotations

import logging
import sys

from app.gui_app import RuntimeGuiApp


logger = logging.getLogger(__name__)


def main() -> int:
    try:
        app = RuntimeGuiApp()
        app.run()
        return 0
    except KeyboardInterrupt:
        logger.info("GUI interrupted by user")
        return 0
    except Exception:
        logging.basicConfig(level=logging.ERROR)
        logger.exception("GUI startup failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
