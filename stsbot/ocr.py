"""Local OCR: PaddleOCR (PP-OCRv5) on the GPU. Adapted from the author's screen assistant.

    engine = Ocr()
    for line in engine.read(image):          # BGR image or crop
        print(line.text, line.box, line.confidence)
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import cv2
import numpy as np

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

Box = tuple[int, int, int, int]  # x, y, w, h in the input image's pixels


@dataclass
class Line:
    text: str
    box: Box
    confidence: float

    @property
    def center(self) -> tuple[float, float]:
        x, y, w, h = self.box
        return x + w / 2, y + h / 2


class Ocr:
    def __init__(self, device: str = "gpu:0", models: str = "server"):
        self.device = device
        self.models = models
        self._ocr = None
        self._rec = None

    def _load(self):
        from paddleocr import PaddleOCR

        self._ocr = PaddleOCR(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            text_detection_model_name=f"PP-OCRv5_{self.models}_det",
            text_recognition_model_name=f"PP-OCRv5_{self.models}_rec",
            text_det_limit_type="max",
            text_det_limit_side_len=2560,
            text_rec_score_thresh=0.0,
            device=self.device,
        )

    def read(self, image: np.ndarray, scale: float = 1.0) -> list[Line]:
        """Detect and read every text line. `scale` > 1 enlarges small crops first."""
        if self._ocr is None:
            self._load()
        img = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC) if scale != 1 else image
        out: list[Line] = []
        for res in self._ocr.predict(img):
            for text, score, poly in zip(res["rec_texts"], res["rec_scores"], res["rec_polys"]):
                if not text.strip():
                    continue
                pts = np.asarray(poly, dtype=np.float32).reshape(-1, 2) / scale
                x0, y0 = np.floor(pts.min(axis=0)).astype(int)
                x1, y1 = np.ceil(pts.max(axis=0)).astype(int)
                out.append(Line(text.strip(), (int(x0), int(y0), int(x1 - x0), int(y1 - y0)), float(score)))
        return sorted(out, key=lambda l: (l.box[1], l.box[0]))
