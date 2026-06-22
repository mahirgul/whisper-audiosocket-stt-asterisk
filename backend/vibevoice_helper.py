import os
import torch
import traceback

def load_vibevoice_model(device: str, compute_type_config: str, cache_dir: str):
    """
    Loads VibeVoice processor and model from the cache directory.
    Uses torch.bfloat16 or torch.float32 depending on GPU capability.
    """
    try:
        from transformers import AutoProcessor, VibeVoiceAsrForConditionalGeneration
    except ImportError:
        raise ImportError(
            "The 'transformers' library is required to run VibeVoice models. "
            "Please install it using: pip install 'transformers>=5.3.0'"
        )

    print(f"[VibeVoice] Loading microsoft/VibeVoice-ASR-HF on device: {device}...")
    processor = AutoProcessor.from_pretrained(
        "microsoft/VibeVoice-ASR-HF",
        cache_dir=cache_dir
    )

    # Resolve dtype based on device and compute type configuration
    if device == "cuda":
        torch_dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        if compute_type_config == "float32":
            torch_dtype = torch.float32
    else:
        torch_dtype = torch.float32

    print(f"[VibeVoice] Using torch_dtype: {torch_dtype}")
    
    # Load model
    model = VibeVoiceAsrForConditionalGeneration.from_pretrained(
        "microsoft/VibeVoice-ASR-HF",
        cache_dir=cache_dir,
        device_map=device if device == "cuda" else "cpu",
        torch_dtype=torch_dtype
    )
    return model, processor

def transcribe_vibevoice(model_data, audio_path: str, options: dict) -> dict:
    """
    Transcribes audio using VibeVoice model and formats the output
    to match the standard WASA segment response structure.
    """
    model, processor = model_data
    
    # Prepare audio input using VibeVoice processor
    # apply_transcription_request handles audio reading and prompt formatting
    prompt = options.get("initial_prompt", "")
    kwargs = {}
    if prompt:
        kwargs["prompt"] = prompt

    inputs = processor.apply_transcription_request(
        audio=audio_path,
        **kwargs
    ).to(model.device, model.dtype)

    # Generate token IDs
    output_ids = model.generate(**inputs)
    
    # Extract only the newly generated token IDs
    generated_ids = output_ids[:, inputs["input_ids"].shape[1]:]
    
    # Decode output
    parsed_result = processor.decode(generated_ids, return_format="parsed")[0]
    
    segments = []
    text_parts = []
    
    # Check if parsed_result is a structured list of dictionaries
    if isinstance(parsed_result, list):
        for utterance in parsed_result:
            # Keys in parsed VibeVoice dict: "Start", "End", "Speaker", "Content"
            start_time = utterance.get("Start", 0.0)
            end_time = utterance.get("End", 0.0)
            spk = utterance.get("Speaker", 0)
            content = utterance.get("Content", "").strip()
            
            if content:
                labeled_text = f"[Speaker {spk}]: {content}"
                segments.append({
                    "start": start_time,
                    "end": end_time,
                    "text": labeled_text
                })
                text_parts.append(labeled_text)
    else:
        # Fallback to transcription only
        raw_text = processor.decode(generated_ids, return_format="transcription_only")[0]
        text_parts.append(raw_text)
        segments.append({
            "start": 0.0,
            "end": 0.0,
            "text": raw_text
        })
        
    return {
        "segments": segments,
        "text": " ".join(text_parts),
        "language": "en"  # Default to english/auto
    }
