"""Document loading. Each file type registers a loader keyed by extension."""
from pathlib import Path

LOADERS = {}


def register(*extensions):
    def wrap(fn):
        for ext in extensions:
            LOADERS[ext] = fn
        return fn
    return wrap


@register(".txt", ".md")
def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


@register(".pdf")
def load_pdf(path: Path) -> str:
    # Planned for version 2.
    raise NotImplementedError("PDF support is coming in version 2.")


def load_document(path: str) -> str:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"No such file: {path}")
    loader = LOADERS.get(p.suffix.lower())
    if loader is None:
        raise ValueError(f"Unsupported file type '{p.suffix}'. Supported: {sorted(LOADERS)}")
    return loader(p)
