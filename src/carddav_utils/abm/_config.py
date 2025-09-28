import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .._client import CardDavClient
from ._merger import AddressBookMerger


class _ClientConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str
    password: str
    address_book_url: str


class _MergerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    targets: dict[str, _ClientConfig]
    sources: dict[str, _ClientConfig]


def load_address_book_merger(path: Path | str) -> AddressBookMerger:
    """Load the address book merger configuration from a TOML file."""

    if isinstance(path, str):
        path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Configuration file {path} does not exist.")

    config = _MergerConfig.model_validate(tomllib.load(path.open("rb")))

    target_config = {
        target_id: CardDavClient(
            username=target.username,
            password=target.password,
            address_book_url=target.address_book_url,
        )
        for target_id, target in config.targets.items()
    }
    sources_config = {
        source_id: CardDavClient(
            username=source.username,
            password=source.password,
            address_book_url=source.address_book_url,
        )
        for source_id, source in config.sources.items()
    }

    return AddressBookMerger(targets=target_config, sources=sources_config)
