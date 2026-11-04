"""Attach the authenticated recruitment API to the existing radar service."""
from contextlib import asynccontextmanager
from .main import create_app


def install_recruitment(app):
    child = create_app()
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(parent):
        # Mounted ASGI applications do not automatically receive lifespan events.
        async with original_lifespan(parent) as state:
            async with child.router.lifespan_context(child):
                yield state

    app.router.lifespan_context = lifespan
    app.mount('/api/recruitment/mvp', child, name='recruitment')
    app.state.recruitment = child
    return child
