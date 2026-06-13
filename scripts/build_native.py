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

"""Rebuild the `_native` extension and install it into the active environment.

With `editable.rebuild = false`, the extension is not rebuilt on import; run this
(`pixi run build`) after editing `cpp/` or the vendored runtime. It does exactly
what scikit-build-core's rebuild hook would: an incremental `cmake --build`
followed by `cmake --install` into the environment's site-packages.

This deliberately drives cmake directly rather than reinstalling via uv/pip — a uv
editable reinstall serves a cached archive and does not reliably pick up C++
changes, whereas `cmake --build` tracks source mtimes and rebuilds only what
changed.
"""

from __future__ import annotations

import glob
import subprocess
import sys
import sysconfig


def main() -> int:
    build_dirs = sorted(glob.glob("build/*/"))
    if not build_dirs:
        sys.exit("No build/ directory found — run `pixi install` first.")

    # With more than one build dir (e.g. several Python versions), pick the one
    # for the running interpreter, identified by its extension suffix.
    if len(build_dirs) > 1:
        ext = sysconfig.get_config_var("EXT_SUFFIX") or ".so"
        matched = [d for d in build_dirs if glob.glob(d + "_native" + ext)]
        if len(matched) != 1:
            sys.exit(
                f"Expected exactly one build dir for {ext}, found {build_dirs}. "
                "Remove stale build/* dirs and re-run `pixi install`."
            )
        build_dirs = matched

    build_dir = build_dirs[0]
    purelib = sysconfig.get_paths()["purelib"]
    subprocess.run(["cmake", "--build", build_dir], check=True)
    subprocess.run(["cmake", "--install", build_dir, "--prefix", purelib], check=True)
    print(f"rebuilt _native -> {purelib}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
