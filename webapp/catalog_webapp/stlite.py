"""Workarounds for running the app under stlite (Pyodide)."""

from __future__ import annotations

import sys
import time

# Streamlit's spinner delay is 0.5 s (streamlit.elements.spinner.DELAY_SECS);
SPINNER_DELAY = 1


def flush_spinner():
    """Let stlite paint a spinner before a blocking request.

    Pyodide runs Python in a single Web Worker and the urllib requests used by
    ``catalog_webapp.github`` are synchronous.  While such a request blocks,
    Streamlit's messages cannot reach the browser, so a spinner entered just
    before the request would only appear after it finishes.  Sleeping briefly
    first yields to the browser, which paints the spinner; the spinner then
    stays visible while the request blocks.
    """
    if sys.platform == "emscripten":
        time.sleep(SPINNER_DELAY)
