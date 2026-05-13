# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.11.x  | :white_check_mark: |
| < 1.10  | :x:                |

## Reporting a Vulnerability

We take security seriously. If you discover a security vulnerability, please:

1. **Do NOT** open a public issue
2. Email the maintainers with a description of the issue
3. Include steps to reproduce (if applicable)
4. We will respond within 48 hours

## Security Considerations

### API Keys

- **Never commit API keys** to the repository
- Use environment variables or a local `config.json` (gitignored)
- The `config.json.example` template is provided for reference
- If you accidentally commit a key, rotate it immediately

### Data Privacy

- NoteMind processes **local files only** — no data is uploaded except to configured AI API providers
- SQLite status database (`.notemind_status.db`) contains file paths and processing metadata
- AI provider URLs are configurable — choose trusted providers
- Local VLM (MiniMind-V) runs entirely on your machine with no network access

### Input Validation

- All file paths are validated before processing
- AI responses are sanitized before inclusion in output
- File size and content limits prevent resource exhaustion

### Third-Party Dependencies

- Core functionality uses only Python standard library (zero third-party risk)
- Optional format parsers (pymupdf, python-docx, etc.) are pinned to known-safe versions
- Review `requirements.txt` before installing optional dependencies
