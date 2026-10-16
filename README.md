# EC2 Scraping

Geenerate an inventory of the ec2 instances on an aws account and get metadata from them

## Development

```bash
uv sync                      # install deps
uv run pre-commit install    # hooks (commit + pre-push)
uv run ruff check . && uv run ruff format .
uv run ty check
uv run pytest
```

Pre-commit runs ruff + hygiene checks; pre-push runs `ty` and `pytest`.

## Docker

```bash
docker build -t ec2-scraping .
docker run --rm ec2-scraping
```
