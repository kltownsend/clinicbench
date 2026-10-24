"""Contract machinery: load contract documents, model-check them, read the promise graph.

- ``contract_doc``  — load an ``agent_*.xml`` document and extract its FizzBee block.
- ``fizz_check``    — run the ``fizz`` model checker over a contract.
- ``promises``      — read the ``<promises>`` manifest (offers / uses) from any contract or manifest.
"""

from .contract_doc import ContractDoc, find_docs_dir, iter_contract_docs, load_contract_doc
from .fizz_check import FizzResult, fizz_available, model_check
from .promises import Manifest, Offer, Use, iter_manifests, load_manifest

__all__ = [
    "ContractDoc",
    "find_docs_dir",
    "iter_contract_docs",
    "load_contract_doc",
    "FizzResult",
    "fizz_available",
    "model_check",
    "Manifest",
    "Offer",
    "Use",
    "iter_manifests",
    "load_manifest",
]
