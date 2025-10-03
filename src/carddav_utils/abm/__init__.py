"""Address book merger module"""

__all__ = ["AddressBookMerger", "MergerConfig", "load_address_book_merger"]

from ._config import MergerConfig, load_address_book_merger
from ._merger import AddressBookMerger
