Tests
-----

This directory contains placeholders for unit and integration tests.

Notes:
- Many learning-related modules import `torch` at module level. To run tests that exercise the trainer, install PyTorch first (see project README). Alternatively tests can mock `torch` as needed.
- Example (run after installing deps):

```bash
pip install -e .
pytest -q
```

Place tests here that are safe to run without heavy GPU dependencies, or use conditional markers to skip GPU-only tests.
