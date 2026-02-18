"""LLM call logging service for debugging and observability.

This module provides structured logging for all LLM calls in the system.
All classes, methods, and fields are prefixed with 'test_' to clearly
indicate this is debug/test infrastructure, not core application logic.
"""

import os
import threading
from datetime import datetime
from typing import Optional


class TestLLMLogger:
    """Singleton service for logging LLM calls to structured log files.
    
    Logs are written to logs/llm/ with unique filenames per call type.
    Each log includes metadata (provider, model, tokens, timing) and
    the complete prompt/response content.
    """
    
    _instance: Optional["TestLLMLogger"] = None
    _lock = threading.Lock()
    
    def __new__(cls, ctx=None) -> "TestLLMLogger":
        with cls._lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._initialized = False
                cls._instance = instance
            return cls._instance

    def __init__(self, ctx=None) -> None:
        if self._initialized:
            return

        self._ctx = ctx
        self._logs_dir_fallback = os.path.join(os.getcwd(), "logs", "llm")
        os.makedirs(self._logs_dir, exist_ok=True)

    @property
    def _logs_dir(self) -> str:
        if self._ctx is not None:
            return self._ctx.llm_logs_dir
        return self._logs_dir_fallback
        self._test_log_all_enabled = False
        self._write_lock = threading.Lock()
        self._initialized = True
    
    def test_log_call(
        self,
        *,
        stem: str,
        provider: str,
        model: str,
        temperature: float,
        input_prompt: str,
        output_response: str,
        duration_ms: int,
        meeting_id: Optional[str] = None,
        question: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> str:
        """Log an LLM call to a structured file.
        
        Args:
            stem: Call type identifier (e.g., 'meeting_chat', 'summarize', 'generate_title')
            provider: LLM provider name (e.g., 'anthropic', 'openai')
            model: Model identifier (e.g., 'claude-3-sonnet', 'gpt-4o')
            temperature: Sampling temperature used
            input_prompt: Complete prompt sent to LLM
            output_response: Complete response from LLM
            duration_ms: Call duration in milliseconds
            meeting_id: Optional meeting ID for context
            question: Optional user question for chat calls
            system_prompt: Optional system prompt if used
            
        Returns:
            Path to the created log file
        """
        timestamp = datetime.now()
        date_str = timestamp.strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"{stem}_{date_str}.log"
        filepath = os.path.join(self._logs_dir, filename)
        
        # Estimate token counts (rough approximation: ~4 chars per token)
        input_tokens = len(input_prompt) // 4
        output_tokens = len(output_response) // 4
        
        # Build log content
        lines = [
            "=" * 80,
            f"LLM CALL LOG: {stem}",
            "=" * 80,
            "",
            "## METADATA",
            f"Timestamp: {timestamp.isoformat()}",
            f"Provider: {provider}",
            f"Model: {model}",
            f"Temperature: {temperature}",
            f"Duration: {duration_ms}ms",
            f"Input Tokens (est): {input_tokens}",
            f"Output Tokens (est): {output_tokens}",
        ]
        
        if meeting_id:
            lines.append(f"Meeting ID: {meeting_id}")
        if question:
            lines.append(f"User Question: {question}")
        
        lines.extend([
            "",
            "-" * 80,
            "## SYSTEM PROMPT",
            "-" * 80,
            system_prompt if system_prompt else "(none)",
            "",
            "-" * 80,
            "## INPUT PROMPT",
            "-" * 80,
            input_prompt,
            "",
            "-" * 80,
            "## OUTPUT RESPONSE",
            "-" * 80,
            output_response,
            "",
            "=" * 80,
            "END OF LOG",
            "=" * 80,
        ])
        
        content = "\n".join(lines)
        
        with self._write_lock:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
        
        return filepath
    
    def test_list_logs(self) -> list[dict]:
        """List all log files in the logs directory.
        
        Returns:
            List of dicts with 'filename', 'path', 'size', 'modified' keys,
            sorted by modification time (newest first).
        """
        logs = []
        if not os.path.exists(self._logs_dir):
            return logs
        
        for filename in os.listdir(self._logs_dir):
            if not filename.endswith(".log"):
                continue
            filepath = os.path.join(self._logs_dir, filename)
            stat = os.stat(filepath)
            logs.append({
                "filename": filename,
                "path": filepath,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
        
        # Sort by modified time, newest first
        logs.sort(key=lambda x: x["modified"], reverse=True)
        return logs
    
    def test_get_log(self, filename: str) -> Optional[str]:
        """Read the content of a specific log file.
        
        Args:
            filename: Name of the log file (not full path)
            
        Returns:
            File content as string, or None if not found
        """
        # Prevent path traversal
        if ".." in filename or "/" in filename or "\\" in filename:
            return None
        
        filepath = os.path.join(self._logs_dir, filename)
        if not os.path.exists(filepath):
            return None
        
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    
    def test_clear_logs(self) -> int:
        """Delete all log files in the logs directory.
        
        Returns:
            Number of files deleted
        """
        count = 0
        if not os.path.exists(self._logs_dir):
            return count
        
        with self._write_lock:
            for filename in os.listdir(self._logs_dir):
                if not filename.endswith(".log"):
                    continue
                filepath = os.path.join(self._logs_dir, filename)
                try:
                    os.remove(filepath)
                    count += 1
                except OSError:
                    pass
        
        return count
    
    def test_set_log_all(self, enabled: bool) -> None:
        """Enable or disable global logging for all LLM calls.
        
        Args:
            enabled: True to log all calls, False to only log explicit requests
        """
        self._test_log_all_enabled = enabled
    
    def test_get_log_all(self) -> bool:
        """Check if global logging is enabled.
        
        Returns:
            True if all LLM calls are being logged
        """
        return self._test_log_all_enabled
