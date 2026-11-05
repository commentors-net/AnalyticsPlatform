"""Metric Rollup Models."""

from __future__ import annotations

import datetime
from api.app.models.api_key import EnvironmentType


class DailyAppMetric:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class DailyPageMetric:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class DailyGeoMetric:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
