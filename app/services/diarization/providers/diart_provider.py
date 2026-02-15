"""
Diart-based diarization provider for real-time speaker identification.

Diart provides streaming speaker diarization using pyannote models with
an incremental clustering algorithm that improves as conversations progress.

This provider supports both:
- Real-time streaming: process audio chunks as they arrive
- Batch processing: process complete audio files (fallback mode)
"""

from __future__ import annotations

import logging
import threading
from typing import Optional, Callable
import os

from app.services.diarization.providers.base import DiarizationConfig
from app.services.ndjson_debug import dbg as nd_dbg
from app.services.diarization.providers.whisperx_provider import _patch_torch_load


class DiartProvider:
    """Real-time speaker diarization using Diart.
    
    Diart wraps pyannote models for streaming use with ~500ms latency.
    Speaker labels are assigned incrementally and may update as more
    context becomes available.
    """
    
    def __init__(self, config: DiarizationConfig) -> None:
        self._config = config
        self._logger = logging.getLogger("notetaker.diarization.diart")
        self._pipeline = None
        self._inference = None
        self._source = None
        self._lock = threading.Lock()
        self._current_annotations: list[dict] = []
        self._is_streaming = False
        
    def _get_hf_token(self) -> Optional[str]:
        """Get HuggingFace token from config or environment."""
        return self._config.hf_token or os.environ.get("HF_TOKEN")
    
    def _create_pipeline(self, sample_rate: int = 16000):
        """Create the Diart speaker diarization pipeline."""
        try:
            # PyTorch 2.6+ defaults to weights_only=True, which breaks pyannote model loading.
            # Apply the shared patch used by WhisperX before any pyannote loads.
            _patch_torch_load()
            nd_dbg(
                "app/services/diarization/providers/diart_provider.py:_create_pipeline",
                "diart_create_pipeline_enter",
                {
                    "sample_rate": sample_rate,
                    "device": str(getattr(self._config, "device", "") or ""),
                    "performance_level": float(getattr(self._config, "performance_level", 0.0) or 0.0),
                    "hf_token_present": bool(self._get_hf_token()),
                },
                run_id="pre-fix",
                hypothesis_id="H2",
            )
            from diart import SpeakerDiarization, SpeakerDiarizationConfig
            from diart.models import SegmentationModel, EmbeddingModel
            import torch
            
            # Map performance_level (0-1) to latency (0.5-5 seconds)
            # Higher performance = higher latency = better accuracy
            latency = 0.5 + (self._config.performance_level * 4.5)
            
            self._logger.info(
                "Creating Diart pipeline: latency=%.1fs device=%s",
                latency,
                self._config.device,
            )
            
            # Use HuggingFace token for model access
            hf_token = self._get_hf_token()
            if hf_token:
                os.environ["HF_TOKEN"] = hf_token

            # IMPORTANT:
            # diart defaults to `use_hf_token=True` (huggingface-cli login token),
            # but in this app we store the token in config. Passing the string token
            # avoids Model.from_pretrained(...) returning None without raising.
            use_hf_token = hf_token or True
            device = torch.device(self._config.device or "cpu")
            nd_dbg(
                "app/services/diarization/providers/diart_provider.py:_create_pipeline",
                "diart_create_pipeline_token_mode",
                {
                    "device": str(device),
                    "use_hf_token_type": type(use_hf_token).__name__,
                    "use_hf_token_is_bool_true": use_hf_token is True,
                },
                run_id="pre-fix",
                hypothesis_id="H2",
            )
            segmentation = SegmentationModel.from_pyannote("pyannote/segmentation", use_hf_token)
            embedding = EmbeddingModel.from_pyannote("pyannote/embedding", use_hf_token)
            # Preflight: ensure pyannote models actually load (avoid diart LazyModel returning None).
            try:
                import sys
                from pyannote.audio import Model as PyannoteModel
                import torch
                import huggingface_hub
                import diart
                seg_model = PyannoteModel.from_pretrained("pyannote/segmentation", use_auth_token=use_hf_token)
                emb_model = PyannoteModel.from_pretrained("pyannote/embedding", use_auth_token=use_hf_token)
                # Probe HF API so we can distinguish gating/auth vs cache/library issues.
                hf_probe: dict = {}
                try:
                    import requests
                    for model_id in (
                        "pyannote/segmentation",
                        "pyannote/embedding",
                        "pyannote/segmentation-3.0",
                        "pyannote/embedding-2.0",
                    ):
                        try:
                            r = requests.get(
                                f"https://huggingface.co/api/models/{model_id}",
                                headers={"Authorization": f"Bearer {use_hf_token}"} if isinstance(use_hf_token, str) else {},
                                timeout=10,
                            )
                            hf_probe[model_id] = {
                                "status": int(r.status_code),
                                "ok": bool(r.status_code == 200),
                            }
                        except Exception as exc:
                            hf_probe[model_id] = {"status": None, "ok": False, "err": str(exc)[:200]}
                except Exception:
                    pass
                nd_dbg(
                    "app/services/diarization/providers/diart_provider.py:_create_pipeline",
                    "diart_pyannote_preflight",
                    {
                        "seg_is_none": seg_model is None,
                        "seg_type": type(seg_model).__name__ if seg_model is not None else None,
                        "emb_is_none": emb_model is None,
                        "emb_type": type(emb_model).__name__ if emb_model is not None else None,
                        "versions": {
                            "python": sys.version.split(" ")[0],
                            "torch": getattr(torch, "__version__", None),
                            "pyannote_audio": getattr(__import__("pyannote.audio"), "__version__", None),
                            "huggingface_hub": getattr(huggingface_hub, "__version__", None),
                            "diart": getattr(diart, "__version__", None),
                        },
                        "hf_probe": hf_probe,
                    },
                    run_id="pre-fix",
                    hypothesis_id="H2",
                )
                if seg_model is None or emb_model is None:
                    raise RuntimeError("pyannote Model.from_pretrained returned None")
            except Exception as exc:
                import traceback
                nd_dbg(
                    "app/services/diarization/providers/diart_provider.py:_create_pipeline",
                    "diart_pyannote_preflight_error",
                    {
                        "exc_type": type(exc).__name__,
                        "exc_str": str(exc)[:800],
                        "traceback": traceback.format_exc()[-2500:],
                    },
                    run_id="pre-fix",
                    hypothesis_id="H2",
                )
                raise
            
            # Create pipeline config
            pipeline_config = SpeakerDiarizationConfig(
                segmentation=segmentation,
                embedding=embedding,
                step=0.5,  # Process every 500ms
                latency=latency,
                tau_active=0.5,  # Activity threshold
                rho_update=0.3,  # Update threshold
                delta_new=1.0,  # New speaker threshold
                device=device,
                sample_rate=sample_rate,
            )
            
            pipeline = SpeakerDiarization(pipeline_config)
            nd_dbg(
                "app/services/diarization/providers/diart_provider.py:_create_pipeline",
                "diart_create_pipeline_ok",
                {"ok": True},
                run_id="pre-fix",
                hypothesis_id="H2",
            )
            return pipeline
            
        except ImportError as exc:
            nd_dbg(
                "app/services/diarization/providers/diart_provider.py:_create_pipeline",
                "diart_import_error",
                {"exc_type": type(exc).__name__, "exc_str": str(exc)[:600]},
                run_id="pre-fix",
                hypothesis_id="H5",
            )
            self._logger.error(
                "Diart not installed. Install with: pip install diart"
            )
            raise RuntimeError("Diart not installed") from exc
        except Exception as exc:
            import traceback
            error_str = str(exc).lower()
            nd_dbg(
                "app/services/diarization/providers/diart_provider.py:_create_pipeline",
                "diart_create_pipeline_error",
                {
                    "exc_type": type(exc).__name__,
                    "exc_str": str(exc)[:800],
                    "traceback": traceback.format_exc()[-2500:],
                },
                run_id="pre-fix",
                hypothesis_id="H2",
            )
            if "403" in error_str or "forbidden" in error_str or "gated" in error_str:
                self._logger.error(
                    "HuggingFace returned 403 Forbidden. Accept pyannote licenses at: "
                    "https://huggingface.co/pyannote/segmentation and "
                    "https://huggingface.co/pyannote/embedding"
                )
                raise RuntimeError(
                    "HuggingFace 403: Accept pyannote licenses"
                ) from exc
            raise
    
    def start_stream(
        self,
        sample_rate: int = 16000,
        on_annotation: Optional[Callable[[list[dict]], None]] = None,
    ) -> None:
        """Start the real-time diarization stream.
        
        Args:
            sample_rate: Audio sample rate (default 16000 for diart)
            on_annotation: Callback called with updated speaker annotations
        """
        with self._lock:
            if self._is_streaming:
                self._logger.warning("Stream already running")
                return
            
            try:
                nd_dbg(
                    "app/services/diarization/providers/diart_provider.py:start_stream",
                    "diart_start_stream_enter",
                    {"sample_rate": sample_rate},
                    run_id="pre-fix",
                    hypothesis_id="H1",
                )
                from diart.sources import AudioSource
                from diart.inference import StreamingInference
                import rx.operators as ops
                
                self._pipeline = self._create_pipeline(sample_rate)
                self._current_annotations = []
                self._is_streaming = True
                
                # Create a custom audio source that we can feed chunks to
                self._audio_buffer = AudioChunkBuffer(sample_rate)
                
                self._logger.info("Diart stream started: sample_rate=%s", sample_rate)
                nd_dbg(
                    "app/services/diarization/providers/diart_provider.py:start_stream",
                    "diart_start_stream_ok",
                    {"ok": True},
                    run_id="pre-fix",
                    hypothesis_id="H1",
                )
                
            except Exception as exc:
                nd_dbg(
                    "app/services/diarization/providers/diart_provider.py:start_stream",
                    "diart_start_stream_error",
                    {"exc_type": type(exc).__name__, "exc_str": str(exc)[:800]},
                    run_id="pre-fix",
                    hypothesis_id="H1",
                )
                self._logger.exception("Failed to start Diart stream: %s", exc)
                self._is_streaming = False
                raise
    
    def feed_chunk(self, audio_bytes: bytes, sample_rate: int = 16000, channels: int = 1) -> list[dict]:
        """Feed an audio chunk and get current speaker annotations.
        
        Args:
            audio_bytes: Raw audio bytes (int16)
            sample_rate: Audio sample rate
            channels: Number of audio channels
            
        Returns:
            List of speaker annotation dicts with start, end, speaker keys
        """
        with self._lock:
            if not self._is_streaming:
                return []
            
            try:
                # First few chunk-level logs only to avoid spam.
                if not hasattr(self, "_dbg_feed_count"):
                    self._dbg_feed_count = 0
                import numpy as np
                import torch
                
                # Convert bytes to numpy array
                audio = np.frombuffer(audio_bytes, dtype=np.int16)
                
                # Convert to mono if stereo
                if channels > 1:
                    audio = audio.reshape(-1, channels)
                    audio = audio.mean(axis=1)
                
                # Normalize to float32 [-1, 1]
                audio = audio.astype(np.float32) / 32768.0
                
                # Resample to 16kHz if needed (diart expects 16kHz)
                if sample_rate != 16000:
                    import scipy.signal as signal
                    num_samples = int(len(audio) * 16000 / sample_rate)
                    audio = signal.resample(audio, num_samples)
                
                # Convert to torch tensor
                waveform = torch.from_numpy(audio).unsqueeze(0)
                
                # Process through pipeline
                # Note: Diart's pipeline returns pyannote Annotation objects
                # We need to convert them to our dict format
                new_annotations = []
                if self._pipeline is not None:
                    # For now, accumulate audio and process periodically
                    self._audio_buffer.add_chunk(waveform)
                    
                    # Process if we have enough audio (at least step size)
                    if self._audio_buffer.duration >= 0.5:
                        annotation = self._process_buffer()
                        if annotation:
                            self._current_annotations = annotation
                            new_annotations = annotation
                if self._dbg_feed_count < 3:
                    self._dbg_feed_count += 1
                    nd_dbg(
                        "app/services/diarization/providers/diart_provider.py:feed_chunk",
                        "diart_feed_chunk",
                        {
                            "bytes": len(audio_bytes),
                            "sample_rate_in": sample_rate,
                            "channels_in": channels,
                            "buffer_duration_s": round(getattr(self._audio_buffer, "duration", 0.0) or 0.0, 3),
                            "annotations": len(self._current_annotations),
                            "new_annotations": len(new_annotations),
                        },
                        run_id="pre-fix",
                        hypothesis_id="H3",
                    )
                
                return new_annotations
                
            except Exception as exc:
                nd_dbg(
                    "app/services/diarization/providers/diart_provider.py:feed_chunk",
                    "diart_feed_chunk_error",
                    {"exc_type": type(exc).__name__, "exc_str": str(exc)[:800]},
                    run_id="pre-fix",
                    hypothesis_id="H3",
                )
                self._logger.warning("Failed to process audio chunk: %s", exc)
                return self._current_annotations
    
    def _process_buffer(self) -> list[dict]:
        """Process accumulated audio buffer through Diart pipeline.
        
        Uses Diart's SpeakerDiarization pipeline to process audio and extract
        speaker segments with embeddings and clustering.
        """
        try:
            waveform = self._audio_buffer.get_waveform()
            if waveform is None:
                return []
            
            # #region agent log
            # Track buffer processing for debugging
            buffer_duration = waveform.shape[-1] / 16000.0  # samples / sample_rate
            nd_dbg(
                "app/services/diarization/providers/diart_provider.py:_process_buffer",
                "diart_process_buffer_start",
                {"buffer_duration_s": round(buffer_duration, 3), "waveform_shape": list(waveform.shape)},
                run_id="pre-fix",
                hypothesis_id="H4",
            )
            # #endregion
            
            # Process through the full pipeline (segmentation -> embedding -> clustering)
            # Diart's __call__ expects Sequence[SlidingWindowFeature], not raw arrays
            try:
                import numpy as np
                from pyannote.core import SlidingWindowFeature, SlidingWindow
                
                # Convert from torch tensor to numpy
                if hasattr(waveform, 'numpy'):
                    waveform_np = waveform.squeeze().numpy()  # Remove batch dim, convert to numpy
                else:
                    waveform_np = np.array(waveform.squeeze())
                
                # Ensure 1D array for mono audio, then reshape to (samples, 1) for pyannote
                if waveform_np.ndim > 1:
                    waveform_np = waveform_np.mean(axis=0)
                waveform_np = waveform_np.reshape(-1, 1)  # Shape: (samples, 1 channel)
                
                # Get pipeline config for chunk duration
                chunk_duration = self._pipeline.config.duration  # Default 5 seconds
                chunk_samples = int(chunk_duration * 16000)  # 16kHz sample rate
                
                # Track cumulative time offset for this session
                if not hasattr(self, "_cumulative_offset"):
                    self._cumulative_offset = 0.0
                
                # Split audio into chunks of the expected duration
                total_samples = waveform_np.shape[0]
                all_annotations = []
                
                # #region agent log
                nd_dbg(
                    "app/services/diarization/providers/diart_provider.py:_process_buffer",
                    "diart_waveform_converted",
                    {
                        "waveform_type": type(waveform_np).__name__,
                        "waveform_shape": list(waveform_np.shape),
                        "dtype": str(waveform_np.dtype),
                        "chunk_duration": chunk_duration,
                        "chunk_samples": chunk_samples,
                        "total_samples": total_samples,
                        "num_chunks": (total_samples + chunk_samples - 1) // chunk_samples,
                    },
                    run_id="pre-fix",
                    hypothesis_id="H4",
                )
                # #endregion
                
                # Process each chunk
                chunk_idx = 0
                sample_rate = 16000  # Diart uses 16kHz
                
                for start_sample in range(0, total_samples, chunk_samples):
                    end_sample = min(start_sample + chunk_samples, total_samples)
                    chunk_data = waveform_np[start_sample:end_sample]
                    
                    # Pad last chunk if needed
                    if chunk_data.shape[0] < chunk_samples:
                        padding = np.zeros((chunk_samples - chunk_data.shape[0], 1), dtype=chunk_data.dtype)
                        chunk_data = np.concatenate([chunk_data, padding], axis=0)
                    
                    # Create SlidingWindowFeature with timing info
                    # SlidingWindow defines per-sample timing resolution
                    chunk_start_time = self._cumulative_offset + (start_sample / sample_rate)
                    resolution = SlidingWindow(
                        start=chunk_start_time,
                        duration=1.0 / sample_rate,
                        step=1.0 / sample_rate,
                    )
                    sliding_feature = SlidingWindowFeature(chunk_data, resolution)
                    
                    # Call pipeline with single chunk as sequence
                    try:
                        outputs = self._pipeline([sliding_feature])
                        
                        # Process outputs - each is (Annotation, SlidingWindowFeature)
                        for annotation, _ in outputs:
                            if annotation is not None:
                                for segment, track, speaker in annotation.itertracks(yield_label=True):
                                    all_annotations.append({
                                        "start": segment.start,
                                        "end": segment.end,
                                        "speaker": speaker,
                                    })
                    except Exception as chunk_exc:
                        # #region agent log
                        import traceback
                        nd_dbg(
                            "app/services/diarization/providers/diart_provider.py:_process_buffer",
                            "diart_chunk_error",
                            {
                                "chunk_idx": chunk_idx,
                                "exc_type": type(chunk_exc).__name__,
                                "exc_str": str(chunk_exc)[:600],
                                "traceback": traceback.format_exc()[-1000:],
                            },
                            run_id="pre-fix",
                            hypothesis_id="H4",
                        )
                        # #endregion
                        self._logger.warning("Chunk %d processing failed: %s", chunk_idx, chunk_exc)
                    
                    chunk_idx += 1
                
                # Update cumulative offset for next buffer
                self._cumulative_offset += buffer_duration
                
                # #region agent log
                nd_dbg(
                    "app/services/diarization/providers/diart_provider.py:_process_buffer",
                    "diart_process_buffer_ok",
                    {
                        "returned_annotations": len(all_annotations),
                        "speakers": list(set(a["speaker"] for a in all_annotations)) if all_annotations else [],
                        "cumulative_offset": round(self._cumulative_offset, 3),
                        "chunks_processed": chunk_idx,
                    },
                    run_id="pre-fix",
                    hypothesis_id="H4",
                )
                # #endregion
                
                return all_annotations
                
            except Exception as pipeline_exc:
                # #region agent log
                import traceback
                nd_dbg(
                    "app/services/diarization/providers/diart_provider.py:_process_buffer",
                    "diart_pipeline_call_error",
                    {
                        "exc_type": type(pipeline_exc).__name__,
                        "exc_str": str(pipeline_exc)[:800],
                        "traceback": traceback.format_exc()[-1500:],
                    },
                    run_id="pre-fix",
                    hypothesis_id="H4",
                )
                # #endregion
                self._logger.warning("Diart pipeline call failed: %s", pipeline_exc)
                return []
            
        except Exception as exc:
            nd_dbg(
                "app/services/diarization/providers/diart_provider.py:_process_buffer",
                "diart_process_buffer_error",
                {"exc_type": type(exc).__name__, "exc_str": str(exc)[:800]},
                run_id="pre-fix",
                hypothesis_id="H4",
            )
            self._logger.warning("Buffer processing failed: %s", exc)
            return []
    
    def get_speaker_at(self, timestamp: float) -> Optional[str]:
        """Get the speaker label at a given timestamp.
        
        Args:
            timestamp: Time in seconds from stream start
            
        Returns:
            Speaker label or None if no speaker at that time
        """
        with self._lock:
            for ann in self._current_annotations:
                if ann["start"] <= timestamp < ann["end"]:
                    return ann["speaker"]
            return None
    
    def stop_stream(self) -> list[dict]:
        """Stop the real-time diarization stream.
        
        Returns:
            Final speaker annotations
        """
        with self._lock:
            if not self._is_streaming:
                return []
            
            self._is_streaming = False
            final_annotations = list(self._current_annotations)
            
            # Clean up
            self._pipeline = None
            self._audio_buffer = None
            self._current_annotations = []
            self._cumulative_offset = 0.0  # Reset for next session
            
            self._logger.info("Diart stream stopped: %s annotations", len(final_annotations))
            return final_annotations
    
    def diarize(self, audio_path: str) -> list[dict]:
        """Batch diarization of a complete audio file.
        
        This is a fallback for file-based transcription. Uses Diart's
        file processing mode rather than streaming.
        
        Args:
            audio_path: Path to audio file
            
        Returns:
            List of speaker annotation dicts
        """
        try:
            from diart import SpeakerDiarization, SpeakerDiarizationConfig
            from diart.sources import FileAudioSource
            from diart.inference import StreamingInference
            
            self._logger.info("Diart batch diarization: %s", audio_path)
            
            # Create pipeline for batch processing
            pipeline = self._create_pipeline()
            
            # Use file as audio source
            source = FileAudioSource(audio_path, sample_rate=16000)
            
            # Run inference
            inference = StreamingInference(pipeline, source)
            prediction = inference()
            
            # Convert pyannote Annotation to our dict format
            annotations = []
            for segment, track, speaker in prediction.itertracks(yield_label=True):
                annotations.append({
                    "start": segment.start,
                    "end": segment.end,
                    "speaker": speaker,
                })
            
            self._logger.info(
                "Diart batch complete: %s segments, %s speakers",
                len(annotations),
                len(set(a["speaker"] for a in annotations)),
            )
            
            return annotations
            
        except Exception as exc:
            self._logger.exception("Diart batch diarization failed: %s", exc)
            raise RuntimeError("Diart diarization failed") from exc


class AudioChunkBuffer:
    """Buffer for accumulating audio chunks for Diart processing."""
    
    def __init__(self, sample_rate: int = 16000):
        self._sample_rate = sample_rate
        self._chunks: list = []
        self._total_samples = 0
    
    @property
    def duration(self) -> float:
        """Duration of buffered audio in seconds."""
        return self._total_samples / self._sample_rate
    
    def add_chunk(self, waveform) -> None:
        """Add a waveform chunk to the buffer."""
        import torch
        self._chunks.append(waveform)
        self._total_samples += waveform.shape[-1]
    
    def get_waveform(self):
        """Get concatenated waveform and clear buffer."""
        import torch
        if not self._chunks:
            return None
        waveform = torch.cat(self._chunks, dim=-1)
        self._chunks = []
        self._total_samples = 0
        return waveform
    
    def clear(self) -> None:
        """Clear the buffer."""
        self._chunks = []
        self._total_samples = 0
