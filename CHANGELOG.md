# Changelog

All notable changes to NoteMind will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- Refactor to proper Python package structure (`pip install notemind`)
- CLI subcommands (`notemind init`, `notemind check`)
- `--resume` checkpoint recovery
- Graceful Ctrl+C handling with checkpoint save
- Type hints across all public APIs

## [1.11.0] — 2026-05-12

### Added
- Unsupported file formats now indexed in SQLite only (no MD document created)
- MOC_unsupported.md supports 500-file auto-split with file type labels
- Original file wikilinks use full `original_path` for correct linking
- MD files without headings now get AI "Overview" section fallback
- `--update` mode includes unsupported file incremental refresh

### Changed
- All stored paths normalized to `/` for cross-platform Obsidian vault sync
- `config.json` categories no longer used for classification (source path mirroring)
- minimind-v model code files included in git (weights excluded)

### Fixed
- Windows path separator compatibility across all modules
- `update_existing_docs` content not written after file move
- `update_unsupported_moc` SQLite table name mismatch
- SQLite singleton thread safety in concurrent tests

## [1.10.0] — 2026-05-12

### Changed
- **Classification logic**: `category` now mirrors `--source` directory structure instead of AI classification
- **MOC knowledge tree**: Multi-level nesting (up to 5 levels: `##` → `######`)
- **Real-time MOC**: Updates after each file processed
- `MOC_unsupported.md`: Unsupported formats indexed separately

### Added
- `--update` validation mode: fixes existing MD file categories and directory mappings
- Source path mirroring with `compute_source_relative_path()`

### Removed
- `_classify_document` function (AI classification no longer used for categorization)

## [1.9.5] — 2026-05-07

### Fixed
- `classify_input` undefined bug in long/short document branches
- MOC excludes `_failed`, `_archive` directories and unsupported files

## [1.9.0] — 2026-05-07

### Added
- Archive files by category (no longer all in `_archive/`)
- Dynamic classification engine (embedding similarity + AI validation)
- AI chapter-level summaries for long documents
- `reasoning_content` model compatibility (DeepSeek R1, Qwen)
- API availability pre-check before import

### Changed
- MOC wikilink format: `[[filename]] full_path tags`
- Real-time MOC.md updates per document
- Summary max_tokens increased 300→600
- Input truncation limit 5000→8000 characters

## [1.8.0] — 2026-05-07

### Added
- Multi-provider API pool with health tracking and auto-degradation
- Circuit breaker pattern for 429 rate limit recovery
- Local MiniMind-V VLM for offline image description
- SQLite status tracking for file updates
- MD5 deduplication
- Document cross-linking based on similarity

## [1.0.0–1.7.1] — Earlier Releases

Initial development releases with core import pipeline, format parsers, and basic AI analysis.
