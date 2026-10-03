"""Allow `python -m ipostudio` as an alias of the `ipo` console script."""

from ipostudio.cli.main import cli

if __name__ == "__main__":
    cli()
