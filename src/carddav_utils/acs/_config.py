import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .._caldavclient import CalDavClient, CalDavClientConfig
from .._carddavclient import CardDavClient, CardDavClientConfig
from ._syncer import AnniversaryCalendarSyncer


class CalendarConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category_identifier: str
    target: CalDavClientConfig
    sources: dict[str, CardDavClientConfig]


def load_anniversary_calendar_syncer(path: Path | str) -> AnniversaryCalendarSyncer:
    """Load the anniversary calendar syncer configuration from a TOML file."""

    if isinstance(path, str):
        path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Configuration file {path} does not exist.")

    config = CalendarConfig.model_validate(tomllib.load(path.open("rb")))

    target_config = CalDavClient.from_config(config.target)
    sources_config = {
        source_id: CardDavClient.from_config(source)
        for source_id, source in config.sources.items()
    }

    return AnniversaryCalendarSyncer(
        target=target_config,
        sources=sources_config,
        category_identifier=config.category_identifier,
    )
