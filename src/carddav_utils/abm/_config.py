import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .._carddavclient import CardDavClient, CardDavClientConfig
from ._merger import AddressBookMerger


class MergerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    targets: dict[str, CardDavClientConfig]
    sources: dict[str, CardDavClientConfig]


def load_address_book_merger(path: Path | str) -> AddressBookMerger:
    """Load the address book merger configuration from a TOML file."""

    if isinstance(path, str):
        path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Configuration file {path} does not exist.")

    config = MergerConfig.model_validate(tomllib.load(path.open("rb")))

    target_config = {
        target_id: CardDavClient.from_config(target)
        for target_id, target in config.targets.items()
    }
    sources_config = {
        source_id: CardDavClient.from_config(source)
        for source_id, source in config.sources.items()
    }

    return AddressBookMerger(targets=target_config, sources=sources_config)
