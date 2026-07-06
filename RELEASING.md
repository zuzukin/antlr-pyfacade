# Releasing antlrope

How a release goes out. Development happens on `dev`; releases are cut from
`main` by pushing a `vX.Y.Z` tag, which triggers the automated builds below.

## 1. Prepare the release on `dev`

1. Finalize [CHANGELOG.md](CHANGELOG.md): retitle the `Unreleased` section to the
   release version with today's date.
2. Set `src/antlrope/VERSION` to the release version (see the version policy in
   [CONTRIBUTING.md](CONTRIBUTING.md)).
3. Regenerate the example facades so their provenance headers carry the release
   version (`pixi run gen-facade && pixi run gen-schema-facade`), and confirm
   `antlrope up-to-date` passes on both.
4. Run the full verification suite:
   `pixi run test`, `pixi run lint`, `ruff format --check .`,
   `pixi run typecheck`, `pixi run docs-build`, `pixi run asan-test`.
5. Commit, push `dev`, and wait for CI to go green.

## 2. Tag and publish

1. Merge `dev` into `main` and push; wait for the `wheels` workflow on `main`
   (it builds without publishing — a dry run of the release build).
2. Tag and push:

   ```sh
   git tag vX.Y.Z && git push origin vX.Y.Z
   ```

   The tag triggers:

   - **wheels** — abi3 wheels for linux (x86_64 + aarch64), macOS (x86_64 +
     arm64), and Windows (amd64), plus the sdist, published to PyPI via the
     project's trusted (OIDC) publisher — no token needed.
   - **docs** — the versioned documentation site deployed to gh-pages under
     `X.Y` with the `latest` alias (mike). One-time setup after the very first
     deploy: `pixi run docs-set-default` points the site root at `latest`.

3. Create a GitHub release from the tag, pasting the CHANGELOG entry.

## 3. conda-forge

The conda recipe lives in [conda-recipe/](conda-recipe/) (rattler-build format).
It builds from the **PyPI sdist**, so it can only be updated after step 2.

- **First release**: copy `conda-recipe/` to
  `conda-forge/staged-recipes` under `recipes/antlrope/`, set `version` to the
  released version and `sha256` to the sdist's hash
  (`shasum -a 256 dist/antlrope-X.Y.Z.tar.gz`, or from the PyPI file listing),
  and open a PR. Once merged, conda-forge creates the feedstock.
- **Later releases**: the conda-forge autotick bot opens a version-bump PR on
  the feedstock automatically; review and merge it there.

## 4. After the release

- Bump `src/antlrope/VERSION` on `dev` to the next patch (and start a fresh
  `Unreleased` CHANGELOG section) so dev builds are distinguishable from the
  release.
- Announce where users are: the ANTLR discussions/mailing list, etc.
