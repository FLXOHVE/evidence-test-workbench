"""Offline compiler for evidence-linked test case drafts.

Input claims are caller assertions. Compilation does not verify their truth,
approve test cases, invoke a model, or execute product tests.
"""

from .module_generation import GenerationError, compile_module

__version__ = "0.1.0"
__all__ = ["GenerationError", "compile_module"]
