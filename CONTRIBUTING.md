# Contributing

Thanks for your interest in Bigbrain! Issues and pull requests are welcome.

## Ground rules

- **Python 3 standard library only.** No third-party dependencies.
- **Never touch `AGENTS.md`, `CLAUDE.md`, or global Codex/Claude config.** Any new write path
  must go through the guard in `scripts/bigbrain/agents_md.py`.
- **Keep lessons and session data out of the repo.** They belong under `~/.bigbrain` and
  `.bigbrain/`, both of which stay untracked.
- **No real API calls in tests.** Use `scripts/mock_server.py` or `BIGBRAIN_MOCK`.

## Before opening a pull request

```bash
bash tests/run_tests.sh      # must end with ALL TESTS PASSED
```

Add or update tests for behaviour you change, and update `README.md` or `references/` if a
user-visible option changes. Keep pull requests focused: one change per PR is easiest to review.

## Reporting bugs

Please include the command you ran, the `[Bigbrain]` lines it printed, the exit code, and your
Python version. Redact your API key and any private task text.

## License

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE).
