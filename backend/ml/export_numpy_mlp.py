"""Replace the PyTorch network inside models/fraud_models.joblib with its NumPy copy, so serving needs no PyTorch.

Run from backend/ after ml/train_fraud.py (needs torch installed):  python ml/export_numpy_mlp.py
Predictions match PyTorch to about 1e-6.
"""

from __future__ import annotations

import sys
from pathlib import Path

import joblib

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app.merchant.nn_model import NumpyMLP, TorchMLP  # noqa: E402

PATH = BACKEND / "models" / "fraud_models.joblib"


def main() -> None:
    bundle = joblib.load(PATH)
    done = 0
    for entry in bundle["models"].values():
        pipe = entry["pipeline"]
        if hasattr(pipe, "steps") and isinstance(pipe.steps[-1][1], TorchMLP):
            pipe.steps[-1] = (pipe.steps[-1][0], NumpyMLP.from_torch(pipe.steps[-1][1]))
            done += 1
    joblib.dump(bundle, PATH, compress=3)
    print(f"converted {done} network(s) in {PATH}")


if __name__ == "__main__":
    main()
