def hello(name: str = "World") -> str:
    """Return a greeting. A blank name falls back to "World"."""
    return f"Hello, {name.strip() or 'World'}!"
