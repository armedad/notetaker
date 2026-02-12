from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass(frozen=True)
class RealtimeDiarizationConfig:
    """Configuration for real-time (streaming) diarization.
    
    Real-time diarization runs during live transcription to provide
    speaker labels in near real-time. Only diart supports this mode.
    """
    enabled: bool
    provider: str  # "diart" or "none"
    device: str  # "cpu" or "cuda"
    hf_token: Optional[str]
    performance_level: float  # 0.0-1.0, trades latency vs accuracy


@dataclass(frozen=True)
class BatchDiarizationConfig:
    """Configuration for batch (offline) diarization.
    
    Batch diarization runs after transcription completes to provide
    higher quality speaker identification. Supports pyannote, whisperx, diart.
    """
    enabled: bool
    provider: str  # "pyannote", "whisperx", "diart", or "none"
    model: str  # e.g., "pyannote/speaker-diarization-3.1"
    device: str  # "cpu" or "cuda"
    hf_token: Optional[str]


@dataclass(frozen=True)
class DiarizationConfig:
    """Legacy unified diarization config for backwards compatibility.
    
    New code should use RealtimeDiarizationConfig and BatchDiarizationConfig.
    """
    enabled: bool
    provider: str
    model: str
    device: str
    hf_token: Optional[str]
    performance_level: float
    
    @classmethod
    def from_realtime(cls, config: RealtimeDiarizationConfig) -> "DiarizationConfig":
        """Create a DiarizationConfig from a RealtimeDiarizationConfig."""
        return cls(
            enabled=config.enabled,
            provider=config.provider,
            model="",  # Not used for realtime
            device=config.device,
            hf_token=config.hf_token,
            performance_level=config.performance_level,
        )
    
    @classmethod
    def from_batch(cls, config: BatchDiarizationConfig) -> "DiarizationConfig":
        """Create a DiarizationConfig from a BatchDiarizationConfig."""
        return cls(
            enabled=config.enabled,
            provider=config.provider,
            model=config.model,
            device=config.device,
            hf_token=config.hf_token,
            performance_level=0.5,  # Not used for batch
        )


def parse_diarization_config(config_dict: dict) -> tuple[RealtimeDiarizationConfig, BatchDiarizationConfig]:
    """Parse diarization config from config.json.
    
    Supports both new split format and legacy single format:
    
    New format:
        {
            "realtime": {"enabled": true, "provider": "diart", ...},
            "batch": {"enabled": true, "provider": "pyannote", ...}
        }
    
    Legacy format:
        {"enabled": true, "provider": "whisperx", ...}
    
    Returns:
        Tuple of (RealtimeDiarizationConfig, BatchDiarizationConfig)
    """
    # Check for new split format
    if "realtime" in config_dict or "batch" in config_dict:
        realtime_dict = config_dict.get("realtime", {})
        batch_dict = config_dict.get("batch", {})
        
        realtime_config = RealtimeDiarizationConfig(
            enabled=bool(realtime_dict.get("enabled", False)),
            provider=realtime_dict.get("provider", "none"),
            device=realtime_dict.get("device", "cpu"),
            hf_token=realtime_dict.get("hf_token"),
            performance_level=float(realtime_dict.get("performance_level", 0.5)),
        )
        
        batch_config = BatchDiarizationConfig(
            enabled=bool(batch_dict.get("enabled", False)),
            provider=batch_dict.get("provider", "none"),
            model=batch_dict.get("model", "pyannote/speaker-diarization-3.1"),
            device=batch_dict.get("device", "cpu"),
            hf_token=batch_dict.get("hf_token"),
        )
        
        return realtime_config, batch_config
    
    # Legacy single format - map to both configs
    enabled = bool(config_dict.get("enabled", False))
    provider = config_dict.get("provider", "none")
    model = config_dict.get("model", "")
    device = config_dict.get("device", "cpu")
    hf_token = config_dict.get("hf_token")
    performance_level = float(config_dict.get("performance_level", 0.5))
    
    # For legacy config, enable realtime only if provider is diart
    realtime_enabled = enabled and provider.lower() == "diart"
    # For legacy config, enable batch for non-diart providers
    batch_enabled = enabled and provider.lower() != "diart"
    
    realtime_config = RealtimeDiarizationConfig(
        enabled=realtime_enabled,
        provider="diart" if realtime_enabled else "none",
        device=device,
        hf_token=hf_token,
        performance_level=performance_level,
    )
    
    batch_config = BatchDiarizationConfig(
        enabled=batch_enabled,
        provider=provider if batch_enabled else "none",
        model=model,
        device=device,
        hf_token=hf_token,
    )
    
    return realtime_config, batch_config


class DiarizationProvider(Protocol):
    def diarize(self, audio_path: str) -> list[dict]:
        ...
