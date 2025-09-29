import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .._client import CardDavClient, CardDavClientConfig
from ._injector import ProfilePictureInjector
from ._signal import SignalCrawler, SignalCrawlerConfig
from ._telegram import TelegramCrawler, TelegramCrawlerConfig


class PPIConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    telegram_crawler: TelegramCrawlerConfig
    signal_crawler: SignalCrawlerConfig
    targets: dict[str, CardDavClientConfig]


def load_profile_picture_injector(path: Path | str) -> ProfilePictureInjector:
    """Load the address book merger configuration from a TOML file."""

    if isinstance(path, str):
        path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Configuration file {path} does not exist.")

    config = PPIConfig.model_validate(tomllib.load(path.open("rb")))

    target_config = {
        target_id: CardDavClient.from_config(target)
        for target_id, target in config.targets.items()
    }

    return ProfilePictureInjector(
        crawlers=[
            SignalCrawler.from_config(config.signal_crawler),
            TelegramCrawler.from_config(config.telegram_crawler),
        ],
        targets=target_config,
    )
