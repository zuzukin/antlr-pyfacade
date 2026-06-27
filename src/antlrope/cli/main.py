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

"""The `antlrope` command-line entry point: the command group and dispatch.

`antlrope` is a command group. Each subcommand lives in its own module under
`antlrope.cli` and exposes a `register(subparsers)` function; add new commands to
`_SUBCOMMANDS` below. Today the only command is `gen` (antlrope.cli.generate).
"""

from __future__ import annotations

import argparse

from antlrope import __version__
from antlrope.cli import generate

# Each entry is a subcommand module exposing `register(subparsers)`.
_SUBCOMMANDS = (generate,)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="antlrope",
        description="Command-line tools for the antlrope ANTLR runtime.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    for module in _SUBCOMMANDS:
        module.register(subparsers)

    args = parser.parse_args(argv)
    if args.command is None:  # bare `antlrope`: show help and exit cleanly
        parser.print_help()
        return 0
    return args.main(args)


if __name__ == "__main__":
    raise SystemExit(main())
