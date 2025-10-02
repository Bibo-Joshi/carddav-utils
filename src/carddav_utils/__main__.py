import asyncio
import logging
from pathlib import Path
from typing import Annotated

import typer

from carddav_utils.abm import ComparisonMethod, load_address_book_merger
from carddav_utils.ppc import (
    InjectionMethod,
    load_profile_picture_injector,
    load_profile_picture_uploader,
)

app = typer.Typer(pretty_exceptions_enable=False)

logging.basicConfig(
    level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)


def set_loglevel(
    loglevel: str | None = typer.Option(
        "INFO",
        "--loglevel",
        "-l",
        help="Set Log level for carddav_utils (e.g. DEBUG, INFO, WARNING, ERROR, CRITICAL).",
        case_sensitive=False,
        show_default=False,
    ),
) -> None:
    if loglevel:
        level = getattr(logging, loglevel.upper(), None)
        if isinstance(level, int):
            logging.getLogger("carddav_utils").setLevel(level)
        else:
            typer.echo(f"Invalid Log-Level: {loglevel}", err=True)
            raise typer.Exit(code=2)


app.callback()(set_loglevel)


@app.command()
def merge_address_books(
    config_path: Annotated[
        Path,
        typer.Argument(..., help="Path to the configuration file.", exists=True, readable=True),
    ],
    method: Annotated[
        ComparisonMethod,
        typer.Option(..., case_sensitive=False, help="Comparison method to use for merging."),
    ] = ComparisonMethod.CONTENT,
) -> None:
    """Merge address books according to the given configuration and comparison method."""

    async def runner() -> None:
        async with load_address_book_merger(config_path) as merger:
            await merger.do_merge(method)

    asyncio.run(runner())


@app.command()
def inject_profile_pictures(
    config_path: Annotated[
        Path,
        typer.Argument(..., help="Path to the configuration file.", exists=True, readable=True),
    ],
    method: Annotated[
        InjectionMethod,
        typer.Option(
            ..., case_sensitive=False, help="Injection method to use for profile pictures."
        ),
    ] = InjectionMethod.COMPARE_CONTENT,
) -> None:
    """Inject profile pictures into contacts according to the given configuration and
    injection method."""

    async def runner() -> None:
        async with load_profile_picture_injector(config_path) as injector:
            await injector.do_injection(injection_method=method)

    asyncio.run(runner())


@app.command()
def upload_profile_pictures(
    config_path: Annotated[
        Path,
        typer.Argument(..., help="Path to the configuration file.", exists=True, readable=True),
    ],
) -> None:
    """Upload profile pictures to Nextcloud according to the given configuration."""

    async def runner() -> None:
        async with load_profile_picture_uploader(config_path) as uploader:
            await uploader.do_upload()

    asyncio.run(runner())


if __name__ == "__main__":
    app()
