import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

from .._carddavclient import CardDavClient, CardDavClientConfig
from .._nextcloudstorage import NextCloudStorage, NextCloudStorageConfig
from ._directory import DirectoryCrawler, DirectoryCrawlerConfig
from ._injector import ProfilePictureInjector
from ._ncupload import ProfilePictureUploader
from ._signal import SignalCrawler, SignalCrawlerConfig
from ._telegram import TelegramCrawler, TelegramCrawlerConfig

if TYPE_CHECKING:
    from ._base import BaseCrawler


class PPIConfig(BaseModel):
    telegram_crawler: TelegramCrawlerConfig
    signal_crawler: SignalCrawlerConfig
    directory_crawler: DirectoryCrawlerConfig | None = None
    # target ID -> config
    targets: dict[str, CardDavClientConfig]


class PPUConfig(BaseModel):
    telegram_crawler: TelegramCrawlerConfig
    signal_crawler: SignalCrawlerConfig
    directory_crawler: DirectoryCrawlerConfig | None = None
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

    crawlers: list[BaseCrawler] = [
        SignalCrawler.from_config(config.signal_crawler),
        TelegramCrawler.from_config(config.telegram_crawler),
    ]
    if config.directory_crawler is not None:
        crawlers.append(DirectoryCrawler.from_config(config.directory_crawler))

    return ProfilePictureInjector(crawlers=crawlers, targets=target_config)


def load_profile_picture_uploader(path: Path | str) -> ProfilePictureUploader:
    """Load the profile picture uploader configuration from a TOML file."""

    if isinstance(path, str):
        path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Configuration file {path} does not exist.")

    config = PPUConfig.model_validate(tomllib.load(path.open("rb")))

    crawlers: list[BaseCrawler] = [
        SignalCrawler.from_config(config.signal_crawler),
        TelegramCrawler.from_config(config.telegram_crawler),
    ]
    if config.directory_crawler is not None:
        crawlers.append(DirectoryCrawler.from_config(config.directory_crawler))

    return ProfilePictureUploader(
        crawlers=crawlers, nextcloud_storage=NextCloudStorage.from_config(config.nextcloud_storage)
    )
