import whisper
import os
import argparse


def download_models(model_list):
    model_dir = os.path.join(os.getcwd(), "models", "whisper")

    if not os.path.exists(model_dir):
        os.makedirs(model_dir)

    print(f"Models will be downloaded to '{model_dir}'...\n")

    for m in model_list:
        print(f"--- Downloading {m} model... ---")
        try:
            # We use device="cpu" just for downloading to ensure it works everywhere
            whisper.load_model(m, device="cpu", download_root=model_dir)
            print(f"SUCCESS: {m} is ready.\n")
        except Exception as e:
            print(f"ERROR: Could not download {m}! Error: {e}\n")


if __name__ == "__main__":
    ALL_MODELS = ["tiny", "base", "small", "medium", "large-v3", "turbo"]

    parser = argparse.ArgumentParser(description="Download Whisper models locally.")
    parser.add_argument(
        "--all", action="store_true", help="Download all available models"
    )
    parser.add_argument(
        "--model",
        type=str,
        help="Specific model to download (tiny, base, small, medium, large-v3, turbo)",
    )

    args = parser.parse_args()

    if args.all:
        download_models(ALL_MODELS)
    elif args.model:
        if args.model in ALL_MODELS:
            download_models([args.model])
        else:
            print(
                f"Error: '{args.model}' is not a valid model name. "
                f"Choose from: {', '.join(ALL_MODELS)}"
            )
    else:
        # Default behavior: list options
        print("Available models:")
        for m in ALL_MODELS:
            print(f" - {m}")
        print(
            "\nRun with '--all' to download everything, "
            "or '--model <name>' for a specific one."
        )
