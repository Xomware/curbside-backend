# curbside-backend
Curbside API: Python Lambdas on DynamoDB, behind an API Gateway HTTP API with a Cognito JWT authorizer.

- `lambdas/<name>/handler.py`: one Lambda per route, deployed as `curbside-<name with _ as ->`
- `lambdas/common/`: shared helpers, published as the `curbside-shared-packages` layer
- Infrastructure lives in `curbside-infrastructure`

## Develop

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python -m pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Before merging a change to the capture prompt, run the golden set against the live model (it costs a few cents, so it isn't in CI). `--record` refreshes the responses the unit tests replay:

```bash
ANTHROPIC_API_KEY=$(infisical secrets get ANTHROPIC_API_KEY --projectId 93ea4d66-6e05-4111-a245-61d3e27c9d43 --env prod --path /curbside --plain --silent) \
  .venv/bin/python scripts/eval_capture.py --record
```

Fixtures must be synthetic. This repo is public, so no real names or addresses go in tests.

## Deploy

Pushes to `main` that touch `lambdas/` or `requirements.txt` run `deploy.yml`. It calls the shared `deploy-lambda-python.yml@v1` with Infisical folder `/curbside`.
