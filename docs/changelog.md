# Documentation Changelog

All notable changes to the plex-planner documentation are recorded here.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## 2025-04-20

### Changed

- Replaced all personal/machine-specific paths with generic relative paths across all docs and README
- CLI examples now use relative paths (e.g. `_MakeMKV/Oppenheimer` instead of absolute drive paths)
- Output examples use relative paths (e.g. `Movies/...` instead of absolute paths)
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
