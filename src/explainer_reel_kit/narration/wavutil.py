"""WAV helpers based on the standard ``wave`` module (PCM only)."""

from __future__ import annotations

import io
import wave
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from .errors import EngineError, EngineErrorKind


@dataclass(frozen=True)
class WavInfo:
    channels: int
    sample_width: int
    sample_rate: int
    frames: int

    @property
    def duration(self) -> Decimal:
        """Exact duration in seconds (frames / rate)."""
        return Decimal(self.frames) / Decimal(self.sample_rate)


def _read(source: bytes | Path) -> tuple[WavInfo, bytes]:
    handle = io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else open(source, "rb")
    with handle, wave.open(handle, "rb") as reader:
        info = WavInfo(
            channels=reader.getnchannels(),
            sample_width=reader.getsampwidth(),
            sample_rate=reader.getframerate(),
            frames=reader.getnframes(),
        )
        frames = reader.readframes(info.frames)
    return info, frames


def read_info(source: bytes | Path) -> WavInfo:
    """Read WAV parameters. Raises wave.Error / EOFError on a broken file."""
    return _read(source)[0]


def engine_wav_info(audio: bytes) -> WavInfo:
    """Like :func:`read_info`, but classifies a broken engine WAV as MALFORMED_RESPONSE."""
    try:
        return read_info(audio)
    except (wave.Error, EOFError) as cause:
        raise EngineError(
            EngineErrorKind.MALFORMED_RESPONSE,
            f"/synthesis の WAV を解釈できません: {cause}",
            endpoint="/synthesis",
            detail=f"byteLength={len(audio)}",
        ) from cause


def concat(chunks: list[bytes]) -> bytes:
    """Join PCM WAV chunks back to back, with no silence in between.

    All chunks must share channels / sample width / sample rate; a mismatch
    means the engine did not honour the requested output format, which is
    reported as MALFORMED_RESPONSE rather than resampled silently.
    """
    if not chunks:
        raise ValueError("no WAV chunks to concatenate")
    if len(chunks) == 1:
        engine_wav_info(chunks[0])
        return chunks[0]

    first_info: WavInfo | None = None
    frames: list[bytes] = []
    for index, chunk in enumerate(chunks):
        try:
            info, data = _read(chunk)
        except (wave.Error, EOFError) as cause:
            raise EngineError(
                EngineErrorKind.MALFORMED_RESPONSE,
                f"/synthesis の WAV（分割 {index + 1}/{len(chunks)}）を解釈できません: {cause}",
                endpoint="/synthesis",
            ) from cause
        if first_info is None:
            first_info = info
        elif (info.channels, info.sample_width, info.sample_rate) != (
            first_info.channels,
            first_info.sample_width,
            first_info.sample_rate,
        ):
            raise EngineError(
                EngineErrorKind.MALFORMED_RESPONSE,
                "分割合成した WAV の形式が一致しません（チャンネル数・量子化ビット・サンプルレート）。",
                endpoint="/synthesis",
                detail=f"chunk1={first_info}, chunk{index + 1}={info}",
            )
        frames.append(data)

    assert first_info is not None
    out = io.BytesIO()
    with wave.open(out, "wb") as writer:
        writer.setnchannels(first_info.channels)
        writer.setsampwidth(first_info.sample_width)
        writer.setframerate(first_info.sample_rate)
        writer.writeframes(b"".join(frames))
    return out.getvalue()


def silent_wav(duration_sec: float, *, sample_rate: int = 44100, channels: int = 1) -> bytes:
    """Generate a 16-bit PCM silent WAV (used by tests)."""
    frames = round(duration_sec * sample_rate)
    out = io.BytesIO()
    with wave.open(out, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(b"\x00\x00" * channels * frames)
    return out.getvalue()
