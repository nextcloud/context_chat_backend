# AGENTS instructions

- Begin each task by reviewing [PRD.md](PRD.md) and [R2RAPIEndpointsSummary.txt](R2RAPIEndpointsSummary.txt) the repository root. Use the R2RAPIEndpointsSummary.txt to query detailed documentation for endpoints in [r2rdocs.txt](r2rdocs.txt) in the repository root. They describe the pluggable RAG architecture and R2R API.
- Keep CCBE endpoints stable; backend swaps must be controlled via `RAG_BACKEND` environment variable.
- Prefer small, focused commits with clear messages.
- Before committing, run `pre-commit run --files <files>` for any touched files and ensure `ruff`, `pyright`, and `pytest` succeed.
- Ensure all R2R HTTP calls include the proper `X-API-Key` or Bearer token as documented in `r2rdocs.txt`.
- Keep `docs/endpoints.md` and `docs/ccbe_r2r_mapping.md` in sync with the codebase. Update them whenever FastAPI routes or R2R
  interactions change.
