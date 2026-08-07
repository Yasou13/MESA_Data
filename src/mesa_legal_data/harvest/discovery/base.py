from typing import Iterable, Protocol

from mesa_legal_data.harvest.config import HarvestSourceConfig
from mesa_legal_data.harvest.models import DiscoveredDocument


class DiscoveryAdapter(Protocol):
    name: str

    def discover(self, *, plan: HarvestSourceConfig, cursor: dict | None) -> Iterable[DiscoveredDocument]: ...

    def get_cursor(self) -> dict: ...
