"""Delete the rendered application PDFs from object storage. Run once, after deploying.

Applications no longer render a PDF, so every object under the ``pdf/`` prefix that is
not a protocol is orphaned: nothing links to it and nothing will again.

A migration cannot do this. It has a database connection and no MinIO credentials, and
the objects are not rows.

Protocol PDFs live under ``pdf/protocol/`` and are skipped. Everything else under
``pdf/`` is an application render, keyed ``pdf/<application id>/<job id>.pdf``.

    python -m scripts.drop_application_pdfs          # list what would go
    python -m scripts.drop_application_pdfs --delete # actually delete
"""

from __future__ import annotations

import argparse
import asyncio

from app.modules.files.storage import build_object_storage
from app.settings import load_settings

#: Protocol renders share the prefix and must survive.
_KEEP = "pdf/protocol/"
_PREFIX = "pdf/"


async def main(*, delete: bool) -> int:
    settings = load_settings()
    storage = build_object_storage(settings)
    if storage is None:
        print("no object storage configured — nothing to do")
        return 0

    keys = [
        k
        for k in await storage.list_keys()
        if k.startswith(_PREFIX) and not k.startswith(_KEEP)
    ]
    for key in keys:
        if delete:
            await storage.remove(key)
        print(("deleted " if delete else "would delete ") + key)
    print(f"{len(keys)} object(s)" + ("" if delete else " — pass --delete to remove them"))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delete", action="store_true", help="actually delete")
    raise SystemExit(asyncio.run(main(delete=parser.parse_args().delete)))
