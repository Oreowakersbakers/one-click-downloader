# Releasing

Releases are built entirely by GitHub Actions on a clean Windows runner.

1. Update `__version__` in `oneclickdl/_version.py` and `version` in
   `extension/manifest.json` to the same semantic version.
2. Merge the version change into `main` and ensure CI passes.
3. Create and push the matching tag, for example:

   ```powershell
   git tag v0.3.0
   git push origin v0.3.0
   ```

For a local package build on a machine that restricts PowerShell scripts, use:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\package-release.ps1 -Version 0.3.0
```

The release workflow validates the tag, runs both test suites, builds the
portable executable, packages the unpacked browser extension as a ZIP, builds
the Inno Setup installer, writes SHA-256 checksums, and publishes all assets to
a GitHub Release with generated release notes.

No signing certificate or browser-store account is required by this pipeline.
