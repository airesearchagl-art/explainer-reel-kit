"""A TTSEngine that is not AivisSpeech (no HTTP). Shared by tests/narration and the top-level tests."""
from __future__ import annotations

from dataclasses import dataclass, field

from explainer_reel_kit.narration.tts import Voice
from explainer_reel_kit.narration.wavutil import silent_wav

SEC_PER_CHAR = 0.01


@dataclass
class FakeTTS:
    """Each character is 10 ms of silence."""

    name: str = "fake"
    url: str = "http://127.0.0.1:9999"
    voices_: list[Voice] = field(default_factory=lambda: [Voice(808373280, "Fake", "uuid-fake", "ノーマル")])
    spoken: list[tuple[str, int, float, float]] = field(default_factory=list)

    def check(self):
        from explainer_reel_kit.narration.tts import EngineInfo

        return EngineInfo(self.name, self.url, "0.0.1")

    def voices(self) -> list[Voice]:
        return list(self.voices_)

    def synthesize(self, text: str, voice: int, *, speed: float, volume: float) -> bytes:
        self.spoken.append((text, voice, speed, volume))
        return silent_wav(len(text) * SEC_PER_CHAR, sample_rate=44100)

    def reading(self, text: str, voice: int) -> str | None:
        return None


