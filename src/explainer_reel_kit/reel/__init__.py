"""通し生成: 台本から MP4 まで（erkit make）と、音声の合成（mux）。"""
from .make import STAGES, Hooks, MakeError, MakeOptions, MakeResult, MakeStop, make

__all__ = ["Hooks", "MakeError", "MakeOptions", "MakeResult", "MakeStop", "STAGES", "make"]
