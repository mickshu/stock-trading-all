from backend.data_sources.base import BaseDataSource
from backend.data_sources.akshare import AkshareDataSource
from backend.data_sources.tushare import TushareDataSource
from backend.config import settings


_sources: dict[str, BaseDataSource] = {
    "akshare": AkshareDataSource(),
    "tushare": TushareDataSource(),
}


def get_data_source(name: str | None = None) -> BaseDataSource:
    source_name = name or settings.active_data_source
    if source_name not in _sources:
        raise ValueError(f"Unknown data source: {source_name}. Available: {list(_sources.keys())}")
    return _sources[source_name]


def list_data_sources() -> list[str]:
    return list(_sources.keys())


def switch_data_source(name: str) -> None:
    if name not in _sources:
        raise ValueError(f"Unknown data source: {name}")
    settings.active_data_source = name
