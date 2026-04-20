# Documentation Changelog

All notable changes to the plex-planner documentation are recorded here.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## 2025-04-20

### Changed

- Replaced all personal/machine-specific paths with generic placeholders across all docs and README
- CLI examples now use `path/to/rips/Title` for user-supplied input paths
- Tool output examples (rip-guide folder structure) use `<output_root>/_MakeMKV/` to clarify the staging directory
- Output destination examples use relative paths (e.g. `Movies/...`, `TV Shows/...`)
- Config examples use `/path/to/media` placeholder
- Debug log references changed to "OS temp directory" instead of platform-specific paths
- Removed personal Python install path from `.github/copilot-instructions.md`

### Added

- Initial documentation structure in `docs/` folder
- Home page with feature overview and quick start (`index.md`)
- Getting Started section: Installation, Configuration
- User Guide section: Typical Workflow, Rip Guide, Organizing Files, Planning, Snapshots
- CLI Reference page with all subcommands and options
- Architecture overview with data flow diagrams
- Plex Naming Rules reference
- `mkdocs.yml` configuration (ready for MkDocs Material when published)
- This changelog
