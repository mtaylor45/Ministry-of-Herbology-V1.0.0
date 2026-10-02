"""Offline stand-ins for the weather sources. Driven by ``fixtures/``."""

from .fetcher import RECORDED_ON, RecordedFetcher, UnavailableFetcher

__all__ = ["RECORDED_ON", "RecordedFetcher", "UnavailableFetcher"]
