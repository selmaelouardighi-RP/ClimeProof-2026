# Contributing

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
