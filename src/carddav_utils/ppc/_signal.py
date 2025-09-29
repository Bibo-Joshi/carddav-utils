import asyncio
import mimetypes
import re
from collections.abc import AsyncGenerator
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Self

from .._utils import get_logger
from ._base import BaseCrawler, BaseCrawlerConfig, ProfilePictureInfo
from ._utils import phone_number_to_string

_LOGGER = get_logger(Path(__file__), "SignalCrawler")
_PATTERN = re.compile(r"(.*)\s*\((\+?[\d ]+)\).*")


class SignalCrawlerConfig(BaseCrawlerConfig):
    executable_path: str | Path | None = None


class SignalCrawler(BaseCrawler[SignalCrawlerConfig]):
    """Crawler for Signal contacts and their profile pictures.
    Works by calling the `sigtop <https://github.com/tbvdm/sigtop>`__ command line tool to export
    avatars.
    """

    def __init__(self, executable_path: str | Path | None = None):
        self._executable_path = (
            Path(executable_path) if executable_path else Path(__file__).parent / "sigtop.exe"
        )

    @classmethod
    def from_config(cls, config: SignalCrawlerConfig) -> Self:
        return cls(**config.model_dump())

    async def acquire_resources(self) -> None:
        if not self._executable_path.is_file():
            raise FileNotFoundError(f"Signal executable not found at {self._executable_path}")

    async def release_resources(self) -> None:
        pass

    async def crawl(self) -> AsyncGenerator[ProfilePictureInfo]:  # type: ignore[override]
        with TemporaryDirectory() as temp_dir:
            process = await asyncio.create_subprocess_shell(
                " ".join([str(self._executable_path), "export-avatars", str(temp_dir)])
            )
            await process.wait()
            if process.returncode != 0:
                _LOGGER.error(
                    "Signal export-avatars command failed with exit code %d", process.returncode
                )
                return
            for file in Path(temp_dir).iterdir():
                if not (match := _PATTERN.match(file.name)):
                    _LOGGER.debug(
                        "Could not extract phone number from file name: `%s`. Skipping", file.name
                    )
                    continue
                mime_type, _ = mimetypes.guess_type(file.name)
                if not mime_type or not mime_type.startswith("image/"):
                    _LOGGER.warning(
                        "File `%s` does not seem to be an image (mime type: `%s`). Skipping",
                        file.name,
                        mime_type,
                    )
                    continue
                phone_number = phone_number_to_string(match.group(2))
                await asyncio.sleep(0)  # Yield control to the event loop to avoid blocking
                _LOGGER.debug(
                    "Found profile picture for contact `%s` (%s)", match.group(1), phone_number
                )
                yield ProfilePictureInfo(
                    phone_number=phone_number,
                    name=file.stem,
                    photo=file.read_bytes(),
                    mime_type=mime_type,
                )
