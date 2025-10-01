import tomllib
from pathlib import Path

from pydantic import BaseModel

from .._carddavclient import CardDavClient, CardDavClientConfig
from .._nextcloudstorage import NextCloudStorage, NextCloudStorageConfig
from ._injector import ProfilePictureInjector
from ._ncupload import ProfilePictureUploader
from ._signal import SignalCrawler, SignalCrawlerConfig
from ._telegram import TelegramCrawler, TelegramCrawlerConfig


class PPIConfig(BaseModel):
    telegram_crawler: TelegramCrawlerConfig
    signal_crawler: SignalCrawlerConfig
    targets: dict[str, CardDavClientConfig]


class PPUConfig(BaseModel):
    telegram_crawler: TelegramCrawlerConfig
    signal_crawler: SignalCrawlerConfig
    nextcloud_storage: NextCloudStorageConfig


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


def load_profile_picture_uploader(path: Path | str) -> ProfilePictureUploader:
    """Load the profile picture uploader configuration from a TOML file."""

    if isinstance(path, str):
        path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Configuration file {path} does not exist.")

    config = PPUConfig.model_validate(tomllib.load(path.open("rb")))

    return ProfilePictureUploader(
        crawlers=[
            SignalCrawler.from_config(config.signal_crawler),
            TelegramCrawler.from_config(config.telegram_crawler),
        ],
        nextcloud_storage=NextCloudStorage.from_config(config.nextcloud_storage),
    )
