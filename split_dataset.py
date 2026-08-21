import json
import random
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
INPUT_FILE = BASE_DIR / "data/agribotgh_dataset_bilingual_563.json"
OUTPUT_DIR = BASE_DIR / "data/splits"

RANDOM_SEED = 42

TRAIN_RATIO = 0.70
VALIDATION_RATIO = 0.15
TEST_RATIO = 0.15


def main():
    # ---------------------------------------------------------
    # Load dataset
    # ---------------------------------------------------------
    with INPUT_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)

    total = len(data)

    # Check ratio
    if abs(TRAIN_RATIO + VALIDATION_RATIO + TEST_RATIO - 1.0) > 1e-9:
        raise ValueError("Train/validation/test ratios must add up to 1.0")

    if total < 10:
        raise ValueError("Dataset is too small to split safely.")

    # ---------------------------------------------------------
    # Shuffle deterministically
    # ---------------------------------------------------------
    random.seed(RANDOM_SEED)
    shuffled = data.copy()
    random.shuffle(shuffled)

    # ---------------------------------------------------------
    # Calculate split sizes
    # ---------------------------------------------------------
    train_end = int(total * TRAIN_RATIO)
    validation_end = train_end + int(total * VALIDATION_RATIO)

    train_data = shuffled[:train_end]
    validation_data = shuffled[train_end:validation_end]
    test_data = shuffled[validation_end:]

    # ---------------------------------------------------------
    # Create output folder
    # ---------------------------------------------------------
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------
    # Save splits
    # ---------------------------------------------------------
    files = {
        "train.json": train_data,
        "validation.json": validation_data,
        "test.json": test_data,
    }

    for filename, records in files.items():
        output_path = OUTPUT_DIR / filename

        with output_path.open("w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)

        print(f"{filename}: {len(records)} records")

    # ---------------------------------------------------------
    # Final summary
    # ---------------------------------------------------------
    print("\n--- SPLIT SUMMARY ---")
    print(f"Total:       {len(data)}")
    print(f"Training:    {len(train_data)}")
    print(f"Validation:  {len(validation_data)}")
    print(f"Testing:     {len(test_data)}")

    print("\nSaved to:")
    print(OUTPUT_DIR.resolve())


if __name__ == "__main__":
    main()
