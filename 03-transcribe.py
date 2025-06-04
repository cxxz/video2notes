import whisperx
from whisperx.utils import get_writer
import logging
import os
from dotenv import load_dotenv
import argparse
import re
import torch

# Load environment variables
load_dotenv()

HF_TOKEN = os.environ.get('HF_TOKEN')

# Constants
if torch.cuda.is_available():
    logging.info("CUDA device found. Using GPU.")
    WHISPERX_DEVICE = "cuda"
    WHISPERX_BATCH_SIZE = 32
    WHISPERX_DTYPE = "float16"
else:
    logging.warning("CUDA device not found. Using CPU instead.")
    WHISPERX_DEVICE = "cpu"
    WHISPERX_BATCH_SIZE = 8
    WHISPERX_DTYPE = "int8"
    
WHISPERX_ARGS = {"max_line_width": None, "max_line_count": None, "highlight_words": False}
SUPPORTED_FORMATS = {"srt", "vtt", "json"}

def load_whisper_model(model_id, device, vocab=None):
    """Load the Whisper model based on the provided model_id."""
    if re.match(r'^[\w\-]+\/[\w\-]+$', model_id):  # Check if model_id is in <repo_id>/<model_name> format
        if HF_TOKEN is None or not HF_TOKEN.startswith("hf_"):
            raise ValueError("HF_TOKEN is required for models from Hugging Face.")
        logging.info(f"Loading Hugging Face model {model_id} with authentication.")
    else:
        logging.info(f"Loading local model from {model_id}")

    if vocab:
        init_prompt = f"Terms and abbreviations used in this transcription include: {vocab}"
        logging.info(f"Initial prompt for transcription:\n{vocab}")
        whisper_model = whisperx.load_model(model_id,
                                            device,
                                            compute_type=WHISPERX_DTYPE,
                                            asr_options={"initial_prompt": init_prompt})
    else:
        whisper_model = whisperx.load_model(model_id, device, compute_type=WHISPERX_DTYPE)

    return whisper_model

def save_transcription(result, save_dir, filename, output_format, whisperx_args):
    """Helper function to write transcription to a file."""
    writer = get_writer(output_format, save_dir)
    writer(result, f"{filename}", whisperx_args)
    text_file = f"{save_dir}/{filename}.{output_format}"
    logging.info(f"{output_format} file written to {text_file}")
    return text_file

def perform_alignment_and_diarization(result, audio, lang, device):
    """Align words and perform speaker diarization."""
    logging.info("Start word aligning...")
    model_a, metadata = whisperx.load_align_model(language_code=lang, device=device)
    aligned_result = whisperx.align(result["segments"], model_a, metadata, audio, device, return_char_alignments=False)
    logging.info("Alignment done.")

    logging.info("Start diarization...")
    diarize_model = whisperx.DiarizationPipeline(use_auth_token=HF_TOKEN, device=device)
    diarize_segments = diarize_model(audio)
    logging.info("Diarization done.")

    logging.info("Start assigning words to speaker...")
    final_result = whisperx.assign_word_speakers(diarize_segments, aligned_result)
    logging.info("Transcription fully complete.")

    return final_result

def transcribe_audio(audio_file, save_dir, save_format, model, device):
    """Transcribe audio and save in the specified format."""
    filename = os.path.splitext(os.path.basename(audio_file))[0]
    output_format = save_format.lstrip(".")
    
    if output_format not in SUPPORTED_FORMATS:
        logging.error(f"{output_format} not supported")
        return None
    
    logging.info(f"Loading {audio_file}")
    audio = whisperx.load_audio(audio_file)
    
    logging.info(f"Start transcribing with batch size {WHISPERX_BATCH_SIZE}")
    result = model.transcribe(audio, batch_size=WHISPERX_BATCH_SIZE)
    lang = result['language']
    logging.info(f"Transcription complete. Language detected: {lang}")
    
    if output_format == "srt":
        return save_transcription(result, save_dir, filename, output_format, WHISPERX_ARGS)
    
    # Perform alignment and diarization for non-SRT formats
    result = perform_alignment_and_diarization(result, audio, lang, device)
    
    # Save transcription based on output format
    if output_format in {"vtt", "json"}:
        return save_transcription(result, save_dir, filename, output_format, WHISPERX_ARGS if output_format == "vtt" else None)
    
def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Transcribe audio files with WhisperX.")
    parser.add_argument("-a", "--audio_path", required=True, help="Path to the input audio file")
    parser.add_argument("-s", "--slides_dir", required=False, help="Path to the slides directory")
    parser.add_argument("-o", "--output", default=".", help="Output directory to save transcriptions")
    parser.add_argument("-f", "--format", choices=["srt", "vtt", "json"], default="json", help="Output format (srt, vtt, json)")
    parser.add_argument("-m", "--model_id", default="large-v3", help="Whisper model ID or local path")
    
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_arguments()
    slides_dir = args.slides_dir
    vocab = None
    if slides_dir is not None:
        vacab_path = os.path.join(slides_dir, "vocabulary.txt")
        if os.path.exists(vacab_path):
            with open(vacab_path, "r") as f:
                vocab = f.read()
    
    if vocab:
            logging.info(f"Vocabulary loaded from {vacab_path}.")
            logging.info(f"Vocabulary: {vocab}")
            whisper_model = load_whisper_model(args.model_id, WHISPERX_DEVICE, vocab)
    else:
        whisper_model = load_whisper_model(args.model_id, WHISPERX_DEVICE)
    
    transcribe_audio(args.audio_path, args.output, args.format, whisper_model, WHISPERX_DEVICE)
