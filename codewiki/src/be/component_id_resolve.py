"""
Resolve LLM-provided component labels to canonical component IDs used in analysis.

Clustering prompts historically elicit short names (e.g. Java class names) while
the dependency graph keys components by full IDs (e.g. path::Symbol).
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, TypeVar

from codewiki.src.be.dependency_analyzer.models.core import Node

logger = logging.getLogger(__name__)

TNode = TypeVar("TNode", bound=Node)


def resolve_component_id(candidate: str, components: Dict[str, TNode]) -> Optional[str]:
    """
    Map a user/LLM label to a single key in ``components`` if possible.

    Returns:
        Canonical component id, or None if unknown or ambiguous.
    """
    if candidate is None:
        return None
    s = str(candidate).strip()
    if not s:
        return None
    if s in components:
        return s

    matches: list[str] = []
    for cid, comp in components.items():
        if comp.name == s:
            matches.append(cid)
            continue
        if comp.display_name and comp.display_name == s:
            matches.append(cid)
            continue
        if "::" in cid:
            _, tail = cid.split("::", 1)
            if tail == s:
                matches.append(cid)

    if len(matches) == 1:
        logger.debug("Resolved component label %r -> %r", s, matches[0])
        return matches[0]
    if len(matches) > 1:
        logger.warning(
            "Ambiguous component label %r matches %d ids (e.g. %s); skipping",
            s,
            len(matches),
            ", ".join(matches[:5]) + ("..." if len(matches) > 5 else ""),
        )
        return None
    return None


def normalize_clustered_component_lists(module_tree: dict, components: Dict[str, TNode]) -> None:
    """
    In-place: replace ``components`` in each top-level module with resolved canonical ids.
    """
    for module_name, module_info in module_tree.items():
        raw = module_info.get("components", [])
        if not raw:
            module_info["components"] = []
            continue
        out: list[str] = []
        for item in raw:
            rid = resolve_component_id(item, components)
            if rid:
                out.append(rid)
            else:
                logger.warning(
                    "Skipping unknown component %r in module %r after resolution",
                    item,
                    module_name,
                )
        module_info["components"] = out
