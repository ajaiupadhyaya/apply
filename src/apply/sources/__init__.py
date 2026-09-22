"""Where postings come from."""

from . import ats, eightfold, pages
from .ats import Ashby, Greenhouse, Lever, Oracle, Workday
from .base import RawPosting, Source, SourceError, strip_html
from .eightfold import Eightfold
from .pages import NextData

#: Every adapter, by the `ats:` name an employers.yaml entry uses.
ADAPTERS: dict[str, object] = {**ats.ADAPTERS, **pages.ADAPTERS, **eightfold.ADAPTERS}

__all__ = ["ADAPTERS", "Ashby", "Eightfold", "Greenhouse", "Lever", "NextData", "Oracle",
           "Workday",
           "RawPosting", "Source", "SourceError", "strip_html"]
