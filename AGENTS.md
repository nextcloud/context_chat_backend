# AGENTS instructions

- Begin each task by reviewing [PRD.md](PRD.md) and [r2rdocs.txt](r2rdocs.txt) in the repository root. They describe the pluggable RAG architecture and R2R API.
- Keep CCBE endpoints stable; backend swaps must be controlled via `RAG_BACKEND` environment variable.
- Prefer small, focused commits with clear messages.
- Before committing, run `pre-commit run --files <files>` for any touched files and ensure `ruff`, `pyright`, and `pytest` succeed.
- Ensure all R2R HTTP calls include the proper `X-API-Key` or Bearer token as documented in `r2rdocs.txt`.
