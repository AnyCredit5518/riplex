# Planned: MkDocs Material + GitHub Pages

**Status**: Deferred until the repository is published to GitHub.

## Summary

The documentation in `docs/` is written in MkDocs-compatible markdown and the
`mkdocs.yml` configuration is ready. Once the repo is published to GitHub, the
remaining steps are:

1. Update `repo_url` in `mkdocs.yml` with the actual GitHub URL
2. Add `mkdocs-material` to the project's dev dependencies
3. Test locally with `mkdocs serve`
4. Set up GitHub Actions to auto-deploy on push to `main`:
   - Use `mkdocs gh-deploy` or the `peaceiris/actions-gh-pages` action
5. Enable GitHub Pages on the `gh-pages` branch in repo settings

## References

- [MkDocs Material](https://squidfunk.github.io/mkdocs-material/)
- [MkDocs GitHub Pages deployment](https://www.mkdocs.org/user-guide/deploying-your-docs/)
- [GitHub Actions for MkDocs](https://squidfunk.github.io/mkdocs-material/publishing-your-site/)
