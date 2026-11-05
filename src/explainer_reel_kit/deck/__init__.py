"""スライド: 台本からアニメーション付きの .pptx を作る。"""
from .builder import BuildError, BuildResult, build_deck

__all__ = ["BuildError", "BuildResult", "build_deck"]
