"""Minimal AppTest: the page shows the repo and ref from bootstrap.json.

This is the first deliverable: the catalog button opens the app and the page
displays the workflow and ref it was given.  No GitHub call and no token are
needed.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from streamlit.testing.v1 import AppTest  # noqa: E402

APP = Path(__file__).resolve().parents[1] / "app.py"


class BootstrapAppTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        Path(self.tmp.name, "bootstrap.json").write_text(
            json.dumps({"repo": "owner/wf", "ref": "v1.0"}), encoding="utf-8"
        )
        cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, cwd)

    def test_shows_repo_and_ref(self):
        at = AppTest.from_file(str(APP), default_timeout=60)
        at.run()

        self.assertFalse(at.exception, [str(e.value) for e in at.exception])
        text = "\n".join(item.value for item in at.markdown)
        self.assertIn("owner/wf", text)
        self.assertIn("v1.0", text)

    def test_sidebar_offers_token_login(self):
        at = AppTest.from_file(str(APP), default_timeout=60)
        at.run()

        self.assertFalse(at.exception, [str(e.value) for e in at.exception])
        self.assertIn(
            "Personal access token", [item.label for item in at.text_input]
        )
        self.assertIn(
            "Create a token",
            [item.label for item in at.get("link_button")],
        )


if __name__ == "__main__":
    unittest.main()
