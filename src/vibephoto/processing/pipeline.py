"""The develop pipeline: an ordered chain of stages + a memoizing renderer.

The canonical order (White Balance → Exposure → Tone → Presence → Color → Curves
→ HSL/B&W → Color Grade → Detail → Effects) mirrors ``docs/06``. Each *stage* is a
pure function of the buffer and the slice of :class:`EditState` it depends on, so
the :class:`PipelineRenderer` can memoize every stage's output and, when a
parameter changes, recompute only that stage and the ones downstream of it. That
downstream-only invalidation is what keeps slider drags fast: nudging Sharpening
reuses the cached buffer all the way through Detail's input and reruns just the
last couple of stages.

This is a linear chain (sufficient for global develop adjustments); branching
DAGs for local masks attach here in a later phase without changing the renderer.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from vibephoto.processing import lens, ops, profiles, scene_linear
from vibephoto.processing.color import Array
from vibephoto.processing.edit_state import EditState
from vibephoto.processing.image_buffer import ImageBuffer

#: Clarity uses a broad blur (local contrast); Texture a fine one.
_CLARITY_SIGMA_FRAC = 0.03
_TEXTURE_SIGMA_FRAC = 0.008


@dataclass(frozen=True)
class Stage:
    """One pipeline step: a name, the EditState fields it reads, and its op.

    ``output_colorspace`` lets a stage retag the buffer (the RAW tone-map turns a
    scene-linear buffer into display sRGB); ``None`` keeps the input's colorspace.
    """

    name: str
    keys: tuple[str, ...]
    fn: Callable[[Array, EditState], Array]
    output_colorspace: str | None = None

    def cache_key(self, state: EditState) -> str:
        return "|".join(_key_value(getattr(state, key)) for key in self.keys)

    def apply(self, buffer: ImageBuffer, state: EditState) -> ImageBuffer:
        data = self.fn(buffer.data, state)
        colorspace = self.output_colorspace or buffer.colorspace
        return ImageBuffer(data, colorspace)


def _key_value(value: object) -> str:
    if isinstance(value, dict):
        return ",".join(f"{k}={value[k]}" for k in sorted(value))
    return str(value)


def _hsl_or_bw(data: Array, state: EditState) -> Array:
    if state.grayscale:
        return ops.grayscale(data, state.bw_mix)
    return ops.hsl(data, state.hsl_hue, state.hsl_sat, state.hsl_lum)


def _color_grade(data: Array, state: EditState) -> Array:
    return ops.color_grade(
        data,
        (state.grade_shadow_hue, state.grade_shadow_sat, state.grade_shadow_lum),
        (state.grade_mid_hue, state.grade_mid_sat, state.grade_mid_lum),
        (state.grade_highlight_hue, state.grade_highlight_sat, state.grade_highlight_lum),
        state.grade_global_hue,
        state.grade_global_sat,
        state.grade_balance,
        state.grade_blending,
    )


def _display_front() -> tuple[Stage, ...]:
    """Basic tone for an already display-referred image (JPEG, or a stacked layer)."""
    return (
        Stage("white_balance", ("temp", "tint"),
              lambda d, s: ops.white_balance(d, s.temp, s.tint)),
        Stage("exposure", ("exposure",), lambda d, s: ops.exposure(d, s.exposure)),
        Stage("contrast", ("contrast",), lambda d, s: ops.contrast(d, s.contrast)),
        Stage("tone", ("highlights", "shadows", "whites", "blacks"),
              lambda d, s: ops.tone_regions(d, s.highlights, s.shadows, s.whites, s.blacks)),
    )


def _linear_front() -> tuple[Stage, ...]:
    """Scene-linear basic tone for a RAW: WB/exposure/tone in linear, then tone-map.

    The tone-map retags the buffer to display sRGB, so every downstream stage runs
    in display space exactly as it does for a JPEG.
    """
    return (
        Stage("wb_kelvin", ("wb_kelvin", "wb_tint"),
              lambda d, s: scene_linear.white_balance_kelvin(d, s.wb_kelvin, s.wb_tint)),
        Stage("highlight_recon", ("highlight_recovery",),
              lambda d, s: scene_linear.reconstruct_highlights(d, s.highlight_recovery)),
        Stage("exposure_linear", ("exposure",),
              lambda d, s: scene_linear.exposure_linear(d, s.exposure)),
        Stage("tone_linear", ("highlights", "shadows", "whites", "blacks"),
              lambda d, s: scene_linear.tone_linear(
                  d, s.highlights, s.shadows, s.whites, s.blacks)),
        Stage("tonemap", (), lambda d, s: scene_linear.tonemap(d), output_colorspace="srgb"),
        Stage("contrast", ("contrast",), lambda d, s: ops.contrast(d, s.contrast)),
    )


def _display_tail() -> tuple[Stage, ...]:
    """Profile → presence → curves → HSL → grade → detail → effects (display space)."""
    return (
        Stage("profile", ("profile",), lambda d, s: profiles.apply_profile(d, s.profile)),
        Stage("lens_geometry", ("lens_distortion", "lens_ca"),
              lambda d, s: lens.correct_chromatic_aberration(
                  lens.correct_distortion(d, s.lens_distortion), s.lens_ca)),
        Stage("lens_vignetting", ("lens_vignetting",),
              lambda d, s: lens.correct_vignetting(d, s.lens_vignetting)),
        Stage("texture", ("texture",),
              lambda d, s: ops.local_contrast(d, s.texture, _TEXTURE_SIGMA_FRAC)),
        Stage("clarity", ("clarity",),
              lambda d, s: ops.local_contrast(d, s.clarity, _CLARITY_SIGMA_FRAC)),
        Stage("dehaze", ("dehaze",), lambda d, s: ops.dehaze(d, s.dehaze)),
        Stage("vibrance", ("vibrance", "saturation"),
              lambda d, s: ops.vibrance_saturation(d, s.vibrance, s.saturation)),
        Stage("parametric_curve", ("park_highlights", "park_lights", "park_darks", "park_shadows"),
              lambda d, s: ops.parametric_curve(
                  d, s.park_highlights, s.park_lights, s.park_darks, s.park_shadows)),
        Stage("point_curves", ("curve_rgb", "curve_red", "curve_green", "curve_blue"),
              lambda d, s: ops.point_curves(
                  d, s.curve_rgb, s.curve_red, s.curve_green, s.curve_blue)),
        Stage("hsl", ("grayscale", "hsl_hue", "hsl_sat", "hsl_lum", "bw_mix"), _hsl_or_bw),
        Stage(
            "color_grade",
            ("grade_shadow_hue", "grade_shadow_sat", "grade_shadow_lum",
             "grade_mid_hue", "grade_mid_sat", "grade_mid_lum",
             "grade_highlight_hue", "grade_highlight_sat", "grade_highlight_lum",
             "grade_global_hue", "grade_global_sat", "grade_balance", "grade_blending"),
            _color_grade,
        ),
        Stage("sharpen", ("sharpen_amount", "sharpen_radius", "sharpen_detail", "sharpen_masking"),
              lambda d, s: ops.sharpen(
                  d, s.sharpen_amount, s.sharpen_radius, s.sharpen_detail, s.sharpen_masking)),
        Stage("noise", ("noise_luminance", "noise_color"),
              lambda d, s: ops.noise_reduction(d, s.noise_luminance, s.noise_color)),
        Stage("vignette", ("vignette_amount", "vignette_midpoint"),
              lambda d, s: ops.vignette(d, s.vignette_amount, s.vignette_midpoint)),
        Stage("grain", ("grain_amount",), lambda d, s: ops.grain(d, s.grain_amount)),
    )


#: Stages skipped in a *draft* (live, interactive) render: the gaussian-blur-heavy
#: presence/detail/effects ops. They dominate render cost yet are near-invisible at
#: fit-to-screen, so the live proxy omits them for a smooth drag; the crisp
#: full-resolution render (once edits settle) puts them back. Editing an early
#: control (Exposure) invalidates everything downstream, so without this a single
#: slider drag re-runs every blur each tick.
_DRAFT_SKIP = frozenset(
    {"texture", "clarity", "dehaze", "sharpen", "noise", "vignette", "grain", "lens_geometry"}
)


def build_stages(*, linear_scene: bool = False, draft: bool = False) -> tuple[Stage, ...]:
    """The canonical, ordered develop pipeline.

    ``linear_scene`` selects the RAW front-end (scene-linear WB/exposure/tone + a
    base tone-map); otherwise the display-referred front-end is used for JPEGs and
    for stacked layers (whose input is already developed). ``draft`` drops the
    expensive blur-based stages (:data:`_DRAFT_SKIP`) for fast live previews.
    """
    front = _linear_front() if linear_scene else _display_front()
    stages = front + _display_tail()
    if draft:
        stages = tuple(stage for stage in stages if stage.name not in _DRAFT_SKIP)
    return stages


class PipelineRenderer:
    """Renders an :class:`EditState` over a fixed base buffer, with per-stage memoization."""

    def __init__(
        self,
        base: ImageBuffer,
        stages: tuple[Stage, ...] | None = None,
        *,
        draft: bool = False,
    ) -> None:
        self._base = base
        # A scene-linear base (RAW) gets the linear develop front-end; an sRGB base
        # (JPEG, or the output of a layer below) gets the display front-end.
        if stages is None:
            stages = build_stages(linear_scene=(base.colorspace == "linear"), draft=draft)
        self._stages = stages
        # Per-stage cache: parallel to ``_stages``; each entry is (cumulative_key, output).
        self._cache: list[tuple[str, ImageBuffer]] = []

    @property
    def base(self) -> ImageBuffer:
        return self._base

    def render(self, state: EditState) -> ImageBuffer:
        """Apply the pipeline, reusing cached stage outputs that are unchanged."""
        current = self._base
        cumulative = "base"
        new_cache: list[tuple[str, ImageBuffer]] = []
        reuse = True
        for index, stage in enumerate(self._stages):
            cumulative = f"{cumulative}|{stage.name}:{stage.cache_key(state)}"
            if reuse and index < len(self._cache) and self._cache[index][0] == cumulative:
                current = self._cache[index][1]
                new_cache.append(self._cache[index])
                continue
            reuse = False  # once one stage changes, everything downstream recomputes
            current = stage.apply(current, state)
            new_cache.append((cumulative, current))
        self._cache = new_cache
        return current
