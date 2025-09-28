"""Address book merger module"""

__all__ = ["AddressBookMerger", "ComparisonMethod", "load_address_book_merger"]

from ._config import load_address_book_merger
from ._merger import AddressBookMerger, ComparisonMethod
