from .wikidata import WikidataAdapter

REGISTRY = {WikidataAdapter.name: WikidataAdapter}


def get_adapters(names=None):
    return [REGISTRY[n]() for n in (names or REGISTRY)]
