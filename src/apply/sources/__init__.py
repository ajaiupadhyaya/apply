"""Where postings come from."""

from . import ats, pages
from .ats import Ashby, Greenhouse, Lever, Oracle, Workday
from .base import RawPosting, Source, SourceError, strip_html
from .pages import NextData

#: Every adapter, by the `ats:` name an employers.yaml entry uses.
ADAPTERS: dict[str, object] = {**ats.ADAPTERS, **pages.ADAPTERS}

__all__ = ["ADAPTERS", "Ashby", "Greenhouse", "Lever", "NextData", "Oracle", "Workday",
           "RawPosting", "Source", "SourceError", "strip_html"]
