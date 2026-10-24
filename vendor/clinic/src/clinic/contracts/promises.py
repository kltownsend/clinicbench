"""Read the Promise Theory ``<promises>`` manifest from a contract or manifest document.

Both ``agent_*.xml`` (LLM agents) and ``manifest_*.xml`` (non-LLM agents) carry a
``<promises>`` block of ``<offer>`` (+) and ``<use>`` (-) elements. This module
parses that block into simple dataclasses so the promise-graph verifier can check
binding completeness (every use meets an offer) and condition quenching.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from .contract_doc import find_docs_dir

__all__ = ["Condition", "Offer", "Use", "Manifest", "load_manifest", "iter_manifests"]


@dataclass(frozen=True, slots=True)
class Condition:
    ref: str
    assessed: str | None


@dataclass(frozen=True, slots=True)
class Offer:
    id: str
    type: str
    to: tuple[str, ...]
    conditions: tuple[Condition, ...]


@dataclass(frozen=True, slots=True)
class Use:
    id: str
    frm: str
    quenches: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Manifest:
    agent: str
    offers: tuple[Offer, ...]
    uses: tuple[Use, ...]
    path: Path


def _tokens(value: str | None) -> tuple[str, ...]:
    return tuple(value.split()) if value else ()


def _parse_offer(elem: ET.Element) -> Offer:
    conditions = tuple(
        Condition(ref=c.get("ref", ""), assessed=c.get("assessed"))
        for c in elem.findall("condition")
    )
    return Offer(
        id=elem.get("id", ""),
        type=elem.get("type", ""),
        to=_tokens(elem.get("to")),
        conditions=conditions,
    )


def _parse_use(elem: ET.Element) -> Use:
    return Use(
        id=elem.get("id", ""),
        frm=elem.get("from", ""),
        quenches=_tokens(elem.get("quenches")),
    )


def load_manifest(path: str | os.PathLike[str]) -> Manifest:
    """Parse the ``<promises>`` block of a contract or manifest document."""
    path = Path(path)
    root = ET.fromstring(path.read_text(encoding="utf-8"))
    if root.tag == "agent-instructions":
        agent = root.get("workflow", "")
    elif root.tag == "agent-manifest":
        agent = root.get("agent", "")
    else:
        raise ValueError(f"{path.name}: unexpected root element <{root.tag}>")

    promises = root.find("promises")
    offers: tuple[Offer, ...] = ()
    uses: tuple[Use, ...] = ()
    if promises is not None:
        offers = tuple(_parse_offer(e) for e in promises.findall("offer"))
        uses = tuple(_parse_use(e) for e in promises.findall("use"))
    return Manifest(agent=agent, offers=offers, uses=uses, path=path)


def iter_manifests(docs_dir: str | os.PathLike[str] | None = None):
    """Yield a :class:`Manifest` for every contract and manifest document."""
    docs = find_docs_dir(docs_dir)
    paths = sorted(docs.glob("agent_*.xml")) + sorted(docs.glob("manifest_*.xml"))
    for path in paths:
        yield load_manifest(path)
