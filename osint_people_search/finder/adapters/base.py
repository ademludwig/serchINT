from dataclasses import dataclass, field


@dataclass
class SearchQuery:
    full_name: str
    country: str = ""
    organization: str = ""
    field: str = ""

    def __post_init__(self):
        self.full_name = " ".join(self.full_name.split())
        if len(self.full_name) < 3 or len(self.full_name) > 200:
            raise ValueError("full_name must be between 3 and 200 characters")

    @property
    def context_terms(self):
        return [t.strip() for t in (self.country, self.organization, self.field) if t.strip()]


@dataclass
class RawResult:
    source: str
    url: str
    title: str
    snippet: str = ""
    names: list = field(default_factory=list)  # labels/aliases to compare with the query
    reliability: float = 0.5
    extra: dict = field(default_factory=dict)


class Adapter:
    name = "base"
    allowed_hosts = frozenset()

    def search(self, query, fetcher):  # -> list[RawResult]
        raise NotImplementedError
