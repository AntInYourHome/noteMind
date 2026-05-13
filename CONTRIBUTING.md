# Contributing to NoteMind

Thank you for your interest in contributing! Here's how to get started.

## Development Setup

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/noteMind.git
cd noteMind

# Create a virtual environment
python -m venv venv
source venv/bin/activate  # Linux/macOS
# or: venv\Scripts\activate  (Windows)

# Install in editable mode with dev dependencies
pip install -e ".[all,dev]"

# Verify installation
python -m notemind --version
```

## Running Tests

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_parsers.py -v

# Run with coverage
python -m pytest tests/ --cov=scripts --cov=import
```

We currently have **107 tests** covering parsers, VLM, DFX features, and import pipeline.

## Code Style

- **Type hints**: Add to all new public functions and methods
- **Docstrings**: English, Google-style or reStructuredText
- **Comments**: English preferred; bilingual acceptable for complex business logic
- **Line length**: 120 characters max
- **Imports**: Standard library → third-party → local, sorted alphabetically

## Making Changes

1. Create a branch for your change
2. Write tests first (TDD encouraged)
3. Implement the change
4. Run the full test suite: `python -m pytest tests/ -v`
5. Commit with conventional commit messages:
   - `feat: add new feature`
   - `fix: resolve bug`
   - `refactor: restructure module`
   - `docs: update README`
   - `test: add coverage for X`
6. Open a Pull Request

## Pull Request Guidelines

- Describe **what** changed and **why**
- Reference any related issues
- Include test plan in the PR body
- Keep PRs focused — one logical change per PR

## Architecture Overview

NoteMind processes documents through an 8-stage pipeline:

```
Parse → Clean → Split → AI Analyze → Classify → Build MD → Track Status → Cross-link → MOC
```

Key modules:
- `import.py` — Pipeline orchestrator (being refactored into `src/notemind/pipeline/`)
- `scripts/parsers.py` — Document format parsers
- `scripts/ai_client.py` — Multi-provider AI API pool
- `scripts/analyzer.py` — AI analysis strategies
- `scripts/builder.py` — Markdown document builder
- `scripts/crosslink.py` — Document cross-linking

## Reporting Issues

- **Bugs**: Include reproduction steps, Python version, and error output
- **Feature requests**: Describe the use case and expected behavior
- **Security**: See [SECURITY.md](SECURITY.md) for responsible disclosure
