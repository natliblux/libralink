from collections.abc import Callable
from importlib import import_module

def load_normalizer(name: str) -> Callable[[str], str]:

    try:
        module = import_module(f"normalization.{name}")
    except ImportError as e:
        raise ValueError(f"cannot load normalizer: {name}") from e
    normalizer = getattr(module, "normalize", None)
    if not callable(normalizer):
        raise ValueError(f"normalizer '{name}' must define a normalize() function")
    return normalizer