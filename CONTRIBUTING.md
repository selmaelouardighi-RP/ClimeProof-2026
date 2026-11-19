# Contributing

How to work on this repository: the git workflow, the checks to run before committing, how to
add a data source or metric, and the data-handling rules. For installing and running the
pipeline, see the [README](README.md#quick-start).

## How we work

- **`main` is the stable branch.** It should always pass the tests, and every commit on it is
  pushed to GitHub.
- **One branch per task.** Make changes on a short-lived branch, never directly on `main`. Keep a
  branch to one topic, such as a fix, a feature or a set of docs changes.
- **No pull requests for now.** There is currently a single committer, so a finished branch is
  merged straight into `main` (fast-forward) and then deleted. If more people join, switch to
  pull requests into `main` with a review.

### Branch names

Short, lowercase and descriptive, with a prefix for the kind of change:

| prefix | for | example |
|---|---|---|
| `feature/` | new behaviour or output | `feature/client-summary` |
| `fix/` | bug fixes | `fix/negative-zero-values` |
| `docs/` or `docs_` | documentation only | `docs_overhaul` |

### Everyday workflow

```bash
# 1. start from the latest main
git switch main
git pull

# 2. create a branch for the task
git switch -c feature/<short-name>

# 3. make changes, then run the checks (see below)

# 4. commit, staging files by name rather than `git add .`
git add src/climeproof/<file>.py tests/<test_file>.py
git commit

# 5. push the branch (first time with -u)
git push -u origin feature/<short-name>

# 6. when the task is done: merge into main, push, and delete the branch
git switch main
git merge --ff-only feature/<short-name>
git push origin main
git branch -d feature/<short-name>
git push origin --delete feature/<short-name>
```

If `main` has moved on since the branch was made, `--ff-only` refuses. Bring the branch up to date
first (`git switch feature/<short-name> && git merge main`), rerun the checks, then merge.

### Commit messages

- Start the subject with a verb in the imperative: "Add …", "Fix …", "Remove …", "Clarify …".
  Keep it under about 70 characters, e.g. `Normalise negative zero in metric values`.
- Use the body, after a blank line, for *why* and anything that isn't obvious from the diff.
- One concern per commit. Keep code and documentation changes in separate commits, and keep
  unrelated fixes out of a feature commit.
- Never put a participating facility's name, address or coordinates in a message (see
  [Data handling](#data-handling-and-confidentiality)).

## Before committing

```bash
pytest                       # offline unit tests; must pass
ruff check src tests         # lint
ruff format --check src tests   # formatting (run `ruff format src tests` to fix)
```

Run `pytest -m live` as well when you change how a source is queried. It hits the real public
APIs, so it's slower and depends on them being up.

New behaviour needs offline tests. Use the `FakeHttp` handler in `tests/conftest.py` instead of
calling real APIs (see `tests/test_providers.py`).

## Versioning outputs

Records state the versions that produced them, so a change to what the pipeline outputs needs a
version bump:

| you changed | bump |
|---|---|
| a metric in `catalog.py` (added, renamed, or its definition or threshold) | `SCHEMA_VERSION` in `schema.py` |
| the shape of the record schema in `schema.py` | `SCHEMA_VERSION` |
| any value in `config/pipeline.toml` | `pipeline.config_version` in that file |
| the shape of the client summary in `summary.py` | `SUMMARY_VERSION` |

## Adding a source / metric

1. Add the metric(s) to `catalog.py` with `provider="<name>"` (bump `SCHEMA_VERSION` if it's new).
2. Write `providers/<name>.py`: subclass `PointProvider` (one query per location) or `Provider`
   (vectorised over the whole batch, for gridded stores) and return a `MetricValue` for every
   metric you own. Use `NO_DATA`/`N/A` with a `note`, never omit a field.
3. Register the class in `providers/__init__.py`.
4. Add offline tests with a `FakeHttp` handler (see `tests/test_providers.py`), and document the
   source and its limitations in `docs/sources.md`.
5. Add the metric(s) to the README's [Current coverage](README.md#current-coverage) table and
   update the count. A new source also goes in the [Data sources](README.md#data-sources) table.

A new Python dependency goes in `pyproject.toml`. Put heavy or source-specific packages in an
optional extra, as `wildfire` does, so the core install stays light.

## Data handling and confidentiality

ClimeProof runs this pipeline for participating facilities whose identities are confidential.
The repository itself stays public-data only.

- **Develop and test on public inputs only:** county sets, national facility datasets and public
  landmarks (see `data/inputs/examples/`).
- **Never put a participating facility's name, address or coordinates** in the repository, an
  issue, a test, a fixture or a commit message.
- **Keep in-house runs in the git-ignored folders:** inputs in `data/inputs/private/`, results in
  `outputs/`. Don't copy files from either into a tracked location.
- **Treat the raw-response cache as private too.** `data/cache/` is git-ignored because each
  cached request contains the location it was made for. Don't commit or share it outside
  ClimeProof.
- **If you find anything that identifies a participant** in the repository or its history, flag
  it to ClimeProof and delete it.
