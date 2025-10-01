"""Profile Picture Crawler module"""

__all__ = [
    "BaseCrawler",
    "BaseCrawlerConfig",
    "InjectionMethod",
    "PPIConfig",
    "PPUConfig",
    "ProfilePictureInfo",
    "ProfilePictureInjector",
    "ProfilePictureUploader",
    "SignalCrawler",
    "SignalCrawlerConfig",
    "TelegramCrawler",
    "TelegramCrawlerConfig",
    "load_profile_picture_injector",
    "load_profile_picture_uploader",
]

from .._profilepictureinfo import ProfilePictureInfo
from ._base import BaseCrawler, BaseCrawlerConfig
from ._config import (
    PPIConfig,
    PPUConfig,
    load_profile_picture_injector,
    load_profile_picture_uploader,
)
from ._injector import InjectionMethod, ProfilePictureInjector
from ._ncupload import ProfilePictureUploader
from ._signal import SignalCrawler, SignalCrawlerConfig
from ._telegram import TelegramCrawler, TelegramCrawlerConfig
