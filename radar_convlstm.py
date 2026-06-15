import argparse
import glob
import os
from typing import List, Tuple, Any


from config import SAVE_PATHS

TARGET_SIZE = (252, 252)


def _debug_log(message: str):
    try:
        from debug_utils import debug_log as _dbg
        _dbg(message)
    except Exception:
        print(message)

INPUT_FRAMES = 4   # Eingabe: letzte 4 Radar-Frames
OUTPUT_FRAMES = 4  # Ausgabe: nächste 4 vorhergesagte Frames
# WICHTIG: INPUT_FRAMES == OUTPUT_FRAMES == 4 ist ABSICHTLICH.
# Conv3D gibt shape (batch, INPUT_FRAMES, H, W, 1) aus, da padding="same".
# y_data hat shape (batch, OUTPUT_FRAMES, H, W, 1).
# Shapes sind kompatibel weil INPUT_FRAMES == OUTPUT_FRAMES.
# Kein Reshape/Slice nötig — kein Shape-Mismatch!
SEQUENCE_LENGTH = INPUT_FRAMES + OUTPUT_FRAMES  # = 8 Frames pro Sliding-Window
def _get_model_path() -> str:
    """
    Gibt den aktuellen ConvLSTM-Modellpfad zurück.
    Kann via runtime_overrides.json überschrieben werden:
      {"CONVLSTM_MODEL_PATH": "/pfad/zum/modell.keras"}
    """
    try:
        import runtime_config
        override = runtime_config.get("CONVLSTM_MODEL_PATH", None)
        if override and isinstance(override, str):
            return override
    except Exception:
        pass
    return os.path.join(SAVE_PATHS["models"], "current", "radar_convlstm.keras")


# Modul-Level-Konstante bleibt für Rückwärtskompatibilität
MODEL_PATH = _get_model_path()


def _load_and_preprocess_frame(path: str):
    import cv2
    import numpy as np
    frame = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if frame is None:
        raise ValueError(f"Konnte Radarbild nicht laden: {path}")
    resized = cv2.resize(frame, TARGET_SIZE, interpolation=cv2.INTER_AREA)
    return resized.astype(np.float32) / 255.0


def _build_sliding_windows(frames: List[Any]):
    import numpy as np
    x_samples, y_samples = [], []
    for start_idx in range(0, len(frames) - SEQUENCE_LENGTH + 1):
        window = frames[start_idx : start_idx + SEQUENCE_LENGTH]
        x_samples.append(np.stack(window[:INPUT_FRAMES], axis=0))
        y_samples.append(np.stack(window[INPUT_FRAMES:], axis=0))

    if not x_samples:
        return np.empty((0, INPUT_FRAMES, *TARGET_SIZE, 1), dtype=np.float32), np.empty(
            (0, OUTPUT_FRAMES, *TARGET_SIZE, 1), dtype=np.float32
        )

    x_data = np.array(x_samples, dtype=np.float32)[..., np.newaxis]
    y_data = np.array(y_samples, dtype=np.float32)[..., np.newaxis]
    return x_data, y_data


def _list_radar_frame_paths():
    """B147: Sortierte Radar-PNG-Pfade, gedeckelt auf die letzten CONVLSTM_MAX_FRAMES
    (Sicherheits-Ceiling gegen RAM-Spitzen; bewahrt die JÜNGSTEN Frames, da Nowcasting
    von Aktualität profitiert). Begrenzt NICHT, wie viele der gecappten Frames je Epoche
    gesehen werden — das Streaming nutzt alle."""
    pattern = os.path.join(SAVE_PATHS["radar"], "*.png")
    frame_paths = sorted(glob.glob(pattern))
    try:
        from config import CONVLSTM_MAX_FRAMES as _max_frames
    except Exception:
        _max_frames = 6000
    try:
        import runtime_config as _rc
        _max_frames = int(_rc.get("CONVLSTM_MAX_FRAMES", _max_frames))
    except Exception:
        pass
    if _max_frames and len(frame_paths) > _max_frames:
        frame_paths = frame_paths[-_max_frames:]
    return frame_paths


def _window_start_indices(n_frames: int):
    """B147: Gültige Sliding-Window-Startindizes (Fensterlänge SEQUENCE_LENGTH)."""
    return list(range(0, n_frames - SEQUENCE_LENGTH + 1))


def _load_radar_dataset():
    import numpy as np
    frame_paths = _list_radar_frame_paths()

    if len(frame_paths) < 200:
        _debug_log(
            f"[CONVLSTM] Training übersprungen: nur {len(frame_paths)} Bilder vorhanden (<200)."
        )
        return np.empty((0,)), np.empty((0,))

    frames = [_load_and_preprocess_frame(path) for path in frame_paths]
    x_data, y_data = _build_sliding_windows(frames)
    _debug_log(
        f"[CONVLSTM] Datensatz erstellt: frames={len(frame_paths)}, samples={len(x_data)}"
    )
    return x_data, y_data


def _build_model():
    import tensorflow as tf
    from tensorflow.keras import layers, models

    model = models.Sequential(
        [
            layers.Input(shape=(INPUT_FRAMES, TARGET_SIZE[1], TARGET_SIZE[0], 1)),
            layers.ConvLSTM2D(
                filters=64,
                kernel_size=(3, 3),
                padding="same",
                return_sequences=True,
            ),
            layers.BatchNormalization(),
            layers.ConvLSTM2D(
                filters=64,
                kernel_size=(3, 3),
                padding="same",
                return_sequences=True,
            ),
            layers.BatchNormalization(),
            # kernel_size=(1,3,3): nur räumliche Faltung (Höhe×Breite).
            # (3,3,3) würde Zeitschritte in der Output-Schicht ungewollt mischen —
            # jeder der 4 vorhergesagten Frames soll zeitlich unabhängig sein.
            layers.Conv3D(
                filters=1,
                kernel_size=(1, 3, 3),
                activation="sigmoid",
                padding="same",
            ),
        ]
    )

    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3),
        loss=tf.keras.losses.MeanAbsoluteError(),
    )
    return model


def train_convlstm(batch_size: int = 4, epochs: int = 30):
    """B147: Trainiert das ConvLSTM SPEICHERSCHONEND per Streaming-Generator — pro Batch
    werden nur die benötigten Frames von der Platte gelesen (Peak-RAM ≈ batch_size ×
    SEQUENCE_LENGTH × Frame). ALLE (gecappten) Frames werden je Epoche gesehen — kein
    Qualitätsverlust gegenüber dem früheren Voll-Array-Pfad. Läuft bewusst auch auf dem Pi.
    Train/Val-Split chronologisch (kein Keras-Inline-Split; Generatoren benötigen
    explizite Validierungsdaten, kein Leakage über die Zeitachse)."""
    import numpy as np
    try:
        import tensorflow as tf
    except ModuleNotFoundError as exc:
        _debug_log(f"[CONVLSTM] Training übersprungen: fehlende Abhängigkeit ({exc}).")
        return {"trained": False, "reason": "missing_dependency", "error": str(exc)}

    frame_paths = _list_radar_frame_paths()
    if len(frame_paths) < 200:
        _debug_log(f"[CONVLSTM] Training übersprungen: nur {len(frame_paths)} Bilder (<200).")
        return {"trained": False, "reason": "insufficient_data"}

    starts = _window_start_indices(len(frame_paths))
    if len(starts) < 5:
        return {"trained": False, "reason": "insufficient_data"}

    # Chronologischer 80/20-Split (kein Shuffle über die Zeitachse).
    split = int(len(starts) * 0.8)
    train_starts, val_starts = starts[:split], starts[split:]
    if not val_starts:
        val_starts = train_starts[-1:]

    class _RadarWindowSequence(tf.keras.utils.Sequence):
        """Liest je Batch nur die benötigten Frames (kleiner Fenster-Cache)."""
        def __init__(self, start_indices, paths, batch):
            self._starts = list(start_indices)
            self._paths = paths
            self._batch = max(1, int(batch))
            self._cache = {}

        def __len__(self):
            return (len(self._starts) + self._batch - 1) // self._batch

        def _frame(self, idx):
            f = self._cache.get(idx)
            if f is None:
                f = _load_and_preprocess_frame(self._paths[idx])
                if len(self._cache) > self._batch * SEQUENCE_LENGTH + SEQUENCE_LENGTH:
                    self._cache.clear()
                self._cache[idx] = f
            return f

        def __getitem__(self, b):
            batch_starts = self._starts[b * self._batch:(b + 1) * self._batch]
            xs, ys = [], []
            for s in batch_starts:
                win = [self._frame(s + k) for k in range(SEQUENCE_LENGTH)]
                xs.append(np.stack(win[:INPUT_FRAMES], axis=0))
                ys.append(np.stack(win[INPUT_FRAMES:], axis=0))
            x = np.array(xs, dtype=np.float32)[..., np.newaxis]
            y = np.array(ys, dtype=np.float32)[..., np.newaxis]
            return x, y

    effective_model_path = _get_model_path()
    os.makedirs(os.path.dirname(effective_model_path), exist_ok=True)
    early_stop = tf.keras.callbacks.EarlyStopping(
        monitor="val_loss", patience=5, restore_best_weights=True
    )

    def _run(bs):
        model = _build_model()
        train_seq = _RadarWindowSequence(train_starts, frame_paths, bs)
        val_seq = _RadarWindowSequence(val_starts, frame_paths, bs)
        _debug_log(
            f"[CONVLSTM] Training (streaming) gestartet: windows={len(starts)} "
            f"(train={len(train_starts)}, val={len(val_starts)}), batch_size={bs}, epochs={epochs}"
        )
        hist = model.fit(
            train_seq, validation_data=val_seq, epochs=epochs,
            callbacks=[early_stop], verbose=1,
        )
        return model, hist

    safe_batch_size = 2 if batch_size < 2 else batch_size
    try:
        model, history = _run(safe_batch_size)
    except Exception as exc:
        if "ResourceExhausted" in str(exc) and safe_batch_size > 2:
            _debug_log("[CONVLSTM] Speichermangel erkannt, neuer Versuch mit batch_size=2")
            model, history = _run(2)
        else:
            raise

    model.save(effective_model_path)
    _debug_log(f"[CONVLSTM] Modell gespeichert unter {effective_model_path}")
    return {
        "trained": True,
        "model_path": effective_model_path,
        "epochs_ran": len(history.history.get("loss", [])),
        "windows": len(starts),
    }


def predict_radar_convlstm(latest_4_frames: List[Any]):
    import cv2
    import numpy as np
    if len(latest_4_frames) != INPUT_FRAMES:
        raise ValueError("Es müssen genau 4 Frames übergeben werden.")

    processed_frames = []
    original_shape = latest_4_frames[0].shape[:2]

    for frame in latest_4_frames:
        gray = frame
        if frame.ndim == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        resized = cv2.resize(gray, TARGET_SIZE, interpolation=cv2.INTER_AREA)
        processed_frames.append(resized.astype(np.float32) / 255.0)

    input_tensor = np.array([processed_frames], dtype=np.float32)[..., np.newaxis]

    import tensorflow as tf

    effective_model_path = _get_model_path()
    if not os.path.exists(effective_model_path):
        _debug_log(
            f"[CONVLSTM] Modell nicht gefunden: {effective_model_path} "
            f"— ConvLSTM-Vorhersage übersprungen (noch kein Training?)."
        )
        return None

    model = tf.keras.models.load_model(effective_model_path, compile=False)
    prediction = model.predict(input_tensor, verbose=0)[0, :, :, :, 0]

    restored = []
    for pred_frame in prediction:
        back_scaled = np.clip(pred_frame * 255.0, 0, 255).astype(np.uint8)
        restored.append(cv2.resize(back_scaled, (original_shape[1], original_shape[0]), interpolation=cv2.INTER_AREA))

    return np.array(restored)


def _cli():
    parser = argparse.ArgumentParser(description="ConvLSTM Radar-Modell")
    parser.add_argument("--train", action="store_true", help="ConvLSTM trainieren")
    parser.add_argument("--batch-size", type=int, default=4, help="Batch-Größe (Pi: 4 oder 2)")
    parser.add_argument("--epochs", type=int, default=30, help="Anzahl Epochen")
    args = parser.parse_args()

    if args.train:
        result = train_convlstm(batch_size=args.batch_size, epochs=args.epochs)
        _debug_log(f"[CONVLSTM] Trainingsergebnis: {result}")
    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
