"""The site generator must at least load: no test imported it, so a broken merge reached main."""


def test_web_module_imports():
    import centinela.web  # noqa: F401
