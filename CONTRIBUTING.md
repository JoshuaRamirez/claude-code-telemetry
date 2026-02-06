# Contributing to claude-code-telemetry

## Development Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/JoshuaRamirez/claude-code-telemetry.git
   cd claude-code-telemetry
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt -r requirements-dev.txt
   ```

3. **Run tests:**
   ```bash
   pytest -m unit -v
   ```

4. **Run linter:**
   ```bash
   ruff check hooks/ tests/
   ```

## Testing

All tests are fully mocked -- no real database, network, or file I/O is needed. The test suite runs in under 1 second.

- **Framework:** pytest 9.0 + pytest-cov 7.0
- **Coverage gate:** 90% minimum (currently at 97%)
- **Run with coverage:** `pytest -m unit --cov=hooks --cov-report=term-missing`

### Test Structure

| File | Tests |
|------|-------|
| `test_db_simple_inserts.py` | Database INSERT operations |
| `test_db_complex_operations.py` | Multi-step DB operations |
| `test_hook_entry_points.py` | stdin/stdout JSON I/O for all 8 hooks |
| `test_log_event.py` | Main `log_event()` orchestration |
| `test_health_check.py` | SessionStart health check |
| `test_diagnose_connection_error.py` | Connection error diagnosis |
| `test_parse_transcript.py` | Full transcript parsing |
| `test_parse_transcript_line.py` | Single transcript line parsing |
| `test_git_info.py` | Git branch/commit extraction |
| `test_calculate_cost.py` | Token cost estimation |

## Pull Request Workflow

1. Fork the repository and create a feature branch.
2. Make your changes with tests.
3. Ensure `ruff check hooks/ tests/` passes with no errors.
4. Ensure `pytest -m unit --cov=hooks` passes with >= 90% coverage.
5. Submit a pull request against `master`.

## Code Style

- Ruff enforces linting (E, W, F, I, B, UP rules).
- Line length limit: 120 characters.
- Type hints are used throughout -- use built-in generics (`dict`, `list`, `tuple`) not `typing.Dict` etc.
- Each hook file follows the same stdin-parse-log-stdout pattern.

## Architecture

All hooks follow a consistent pattern:

```
stdin (JSON) -> parse -> db_logger.log_event() -> stdout (JSON)
```

- `hooks/db_logger.py` -- Core database logic (connection, logging functions)
- `hooks/db_*.py` -- Hook entry points (one per event type)
- `hooks/health_check.py` -- SessionStart prerequisite validation
