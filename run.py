import warnings

# Suppress torchaudio deprecation warnings (pyannote uses deprecated APIs)
# These are informational only - functionality is not affected
warnings.filterwarnings("ignore", message=".*torchaudio.*deprecated.*")
warnings.filterwarnings("ignore", message=".*AudioMetaData.*deprecated.*")
warnings.filterwarnings("ignore", message=".*MPEG_LAYER_III.*unknown.*")
warnings.filterwarnings("ignore", message=".*torchaudio.load_with_torchcodec.*")

from app.main import create_app

app = create_app()
