# Copyright 2026 Christopher Barber
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""The committed CLI reference stays in sync with the live `--help` output."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_cli_docs_up_to_date():
    # Runs scripts/gen_cli_docs.py --check in a fresh process (isolating its COLUMNS
    # tweak); non-zero means docs/reference/cli.md drifted from the CLI.
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "gen_cli_docs.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
