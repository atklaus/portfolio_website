# Projects Index

Each project lives in its own folder under `projects/` and should be self-contained.

**Conventions**
- Keep project code in its folder and expose a clean public API in `__init__.py`.
- Use subfolders for assets and data.
`assets/` — PDFs, images, static files.
`model/` — trained models or weights.
`fixtures/` — small sample inputs/outputs.
`tests/` — project tests.
- Streamlit pages live in `pages/` and import from `projects.<name>`.

**Current Projects**
- `bibclean/` — Bibliometrix reference cleaner.
- `landscape_img/` — Landscape image classifier.
- `wnba_success/` — WNBA elite impact projection.
- `ellipses/` — Random ellipse overlap simulator.
- `game_of_life/` — Conway's Game of Life.
- `happy_prime/` — Happy/sad + prime calculator.
- `job_prep/` — Job prep scripts (non-Streamlit).
