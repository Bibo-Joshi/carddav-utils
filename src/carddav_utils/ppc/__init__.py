"""Profile Picture Crawler module"""

__all__ = [
    "BaseCrawler",
    "BaseCrawlerConfig",
    "InjectionMethod",
    "PPIConfig",
    "ParsedPhoneNumber",
    "ProfilePictureInfo",
    "ProfilePictureInjector",
    "SignalCrawler",
    "SignalCrawlerConfig",
    "TelegramCrawler",
    "TelegramCrawlerConfig",
    "load_profile_picture_injector",
]

from ._base import BaseCrawler, BaseCrawlerConfig, ParsedPhoneNumber, ProfilePictureInfo
from ._config import PPIConfig, load_profile_picture_injector
from ._injector import InjectionMethod, ProfilePictureInjector
from ._signal import SignalCrawler, SignalCrawlerConfig
from ._telegram import TelegramCrawler, TelegramCrawlerConfig
