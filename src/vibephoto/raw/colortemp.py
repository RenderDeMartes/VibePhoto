"""Estimate a RAW's as-shot colour temperature from LibRaw calibration data.

Uses the camera's as-shot white-balance multipliers and its XYZ->camera colour
matrix (``rgb_xyz_matrix``) to recover the scene illuminant's chromaticity, then
McCamy's approximation for the correlated colour temperature (CCT). This makes the
Develop white-balance slider read the *true* per-camera Kelvin (e.g. 5339 K) rather
than a value relative to a fixed reference. Pure NumPy; lives in the ``raw`` layer
so :mod:`vibephoto.raw.service` can use it without depending on processing.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def as_shot_temperature(
    camera_wb: Sequence[float], xyz_to_cam: Sequence[Sequence[float]]
) -> float | None:
    """Return the as-shot CCT in Kelvin, or ``None`` if it can't be computed.

    ``camera_wb`` is LibRaw's ``camera_whitebalance`` (R, G, B, G2 multipliers);
    ``xyz_to_cam`` is ``rgb_xyz_matrix`` (rows = camera channels, cols = XYZ).
    """
    try:
        multipliers = np.asarray(camera_wb, dtype=np.float64).reshape(-1)[:3]
        matrix = np.asarray(xyz_to_cam, dtype=np.float64)[:3, :3]
        if multipliers.shape != (3,) or matrix.shape != (3, 3):
            return None
        if not np.isfinite(multipliers).all() or not np.isfinite(matrix).all():
            return None
        if multipliers[1] == 0.0 or abs(float(np.linalg.det(matrix))) < 1e-9:
            return None
        # The scene illuminant in camera space is proportional to 1 / WB multipliers.
        illuminant_cam = 1.0 / np.clip(multipliers, 1e-6, None)
        illuminant_cam = illuminant_cam / illuminant_cam[1]
        xyz = np.linalg.inv(matrix) @ illuminant_cam
        total = float(xyz.sum())
        if total <= 0.0:
            return None
        x, y = xyz[0] / total, xyz[1] / total
        denominator = 0.1858 - y
        if abs(denominator) < 1e-9:
            return None
        n = (x - 0.3320) / denominator
        cct = 449.0 * n**3 + 3525.0 * n**2 + 6823.3 * n + 5520.33
        if not np.isfinite(cct):
            return None
        return float(np.clip(cct, 2000.0, 50000.0))
    except (ValueError, np.linalg.LinAlgError):
        return None
