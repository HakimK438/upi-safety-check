"""Neural network for the fraud models: a PyTorch MLP wrapped as a scikit-learn classifier (so it fits in a Pipeline,
is calibrated like the other models and pickles with joblib).

Design: 3 hidden layers (256-128-64) with batch norm, ReLU and dropout; class-weighted loss for rare fraud; AdamW;
early stopping on the LAST 10% of the training rows (rows are time-ordered, so no look-ahead).
"""

from __future__ import annotations

import numpy as np
from sklearn.base import BaseEstimator, ClassifierMixin

# PyTorch is only needed to TRAIN the network (TorchMLP). The shipped models use NumpyMLP below, so serving needs no PyTorch.


class TorchMLP(BaseEstimator, ClassifierMixin):
    def __init__(self, hidden: tuple[int, ...] = (256, 128, 64), dropout: float = 0.2, lr: float = 2e-3, weight_decay: float = 1e-4,
                 epochs: int = 40, batch_size: int = 1024, patience: int = 5, pos_weight: float = 1.0, random_state: int = 0) -> None:
        self.hidden, self.dropout, self.lr, self.weight_decay = hidden, dropout, lr, weight_decay
        self.epochs, self.batch_size, self.patience, self.pos_weight, self.random_state = epochs, batch_size, patience, pos_weight, random_state

    def _net(self, n_in: int):  # -> torch.nn.Module
        from torch import nn

        layers: list = []
        for h in self.hidden:
            layers += [nn.Linear(n_in, h), nn.BatchNorm1d(h), nn.ReLU(), nn.Dropout(self.dropout)]
            n_in = h
        return nn.Sequential(*layers, nn.Linear(n_in, 1))

    def fit(self, X: np.ndarray, y: np.ndarray) -> "TorchMLP":
        import torch
        from torch import nn

        torch.manual_seed(self.random_state)
        X = np.asarray(X, dtype=np.float32)
        y = np.asarray(y, dtype=np.float32)
        cut = int(len(X) * 0.9)
        Xt, yt, Xv, yv = torch.from_numpy(X[:cut]), torch.from_numpy(y[:cut]), torch.from_numpy(X[cut:]), torch.from_numpy(y[cut:])
        self.classes_ = np.array([0, 1])
        self.net_ = self._net(X.shape[1])
        opt = torch.optim.AdamW(self.net_.parameters(), lr=self.lr, weight_decay=self.weight_decay)
        sched = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, factor=0.5, patience=2)
        loss_fn = nn.BCEWithLogitsLoss(pos_weight=torch.tensor(self.pos_weight))
        best, best_state, bad = np.inf, None, 0
        g = torch.Generator().manual_seed(self.random_state)
        for _ in range(self.epochs):
            self.net_.train()
            for idx in torch.randperm(len(Xt), generator=g).split(self.batch_size):
                if len(idx) < 2:
                    continue
                opt.zero_grad()
                loss_fn(self.net_(Xt[idx]).squeeze(1), yt[idx]).backward()
                opt.step()
            self.net_.eval()
            with torch.no_grad():
                v = float(loss_fn(self.net_(Xv).squeeze(1), yv))
            sched.step(v)
            if v < best - 1e-5:
                best, bad = v, 0
                best_state = {k: t.clone() for k, t in self.net_.state_dict().items()}
            else:
                bad += 1
                if bad >= self.patience:
                    break
        if best_state is not None:
            self.net_.load_state_dict(best_state)
        self.net_.eval()
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        import torch

        with torch.no_grad():
            p = torch.sigmoid(self.net_(torch.from_numpy(np.asarray(X, dtype=np.float32))).squeeze(1)).numpy()
        return np.column_stack([1 - p, p])

    def predict(self, X: np.ndarray) -> np.ndarray:
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)


class NumpyMLP(BaseEstimator, ClassifierMixin):
    """The trained TorchMLP as plain NumPy arrays: same predictions, no PyTorch needed to load or run it.

    In evaluation mode a layer is Linear -> BatchNorm -> ReLU (dropout does nothing), and BatchNorm is a fixed scale and shift,
    so each block folds into one weight matrix and one bias. Build it with `NumpyMLP.from_torch(trained_model)`.
    """

    def __init__(self, weights: list | None = None, biases: list | None = None) -> None:
        self.weights, self.biases = weights, biases
        self.classes_ = np.array([0, 1])

    def fit(self, X: np.ndarray, y: np.ndarray) -> "NumpyMLP":  # noqa: ARG002
        raise NotImplementedError("NumpyMLP only serves a network trained with TorchMLP; train with TorchMLP and convert.")

    def __sklearn_is_fitted__(self) -> bool:
        return self.weights is not None

    @classmethod
    def from_torch(cls, m: "TorchMLP") -> "NumpyMLP":
        import torch

        mods = list(m.net_.eval())
        weights: list[np.ndarray] = []
        biases: list[np.ndarray] = []
        i = 0
        while i < len(mods):
            lin = mods[i]
            W = lin.weight.detach().double().numpy().T  # (in, out)
            b = lin.bias.detach().double().numpy()
            if i + 1 < len(mods) and isinstance(mods[i + 1], torch.nn.BatchNorm1d):
                bn = mods[i + 1]
                scale = bn.weight.detach().double().numpy() / np.sqrt(bn.running_var.detach().double().numpy() + bn.eps)
                W = W * scale
                b = (b - bn.running_mean.detach().double().numpy()) * scale + bn.bias.detach().double().numpy()
                i += 4  # Linear, BatchNorm, ReLU, Dropout
            else:
                i += 1  # the final Linear layer
            weights.append(W.astype(np.float32))
            biases.append(b.astype(np.float32))
        return cls(weights, biases)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        h = np.asarray(X, dtype=np.float32)
        for k, (W, b) in enumerate(zip(self.weights, self.biases)):
            h = h @ W + b
            if k < len(self.weights) - 1:
                h = np.maximum(h, 0.0)
        p = (1.0 / (1.0 + np.exp(-h))).reshape(-1).astype(np.float64)
        return np.column_stack([1 - p, p])

    def predict(self, X: np.ndarray) -> np.ndarray:
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)
