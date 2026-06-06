"""TraceCaliper CLI entrypoint.

This module exposes a Typer application as ``app``. Subcommands for
``inspect``, ``compare``, and ``report`` are wired in later features; the
skeleton here only guarantees that ``tracecaliper --help`` exits cleanly.
"""

from __future__ import annotations

import typer

app = typer.Typer(
    name="tracecaliper",
    help="Trace-first release gate for coding-agent skills.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def _main() -> None:
    """TraceCaliper command-line interface.

    Subcommands (``inspect``, ``compare``, ``report``) are registered in
    later features. This callback ensures ``--help`` works on the bare
    ``tracecaliper`` invocation.
    """


if __name__ == "__main__":
    app()
