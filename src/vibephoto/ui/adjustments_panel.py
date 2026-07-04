"""The Develop adjustments panel — professional sliders + histogram.

A scrollable, spec-driven panel: each control is described once in
:data:`PARAM_GROUPS` and the panel builds a labelled slider for it, grouped into
collapsible sections under a live histogram. Double-clicking a slider resets it.
Tone curves and 3-way colour grading still *render* (e.g. from an imported
preset) — they simply have no dedicated slider here yet.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from vibephoto.processing.edit_state import HSL_BANDS, EditState
from vibephoto.processing.layers import LayerStack
from vibephoto.processing.profiles import PROFILE_NAMES
from vibephoto.ui.color_wheels import ColorGradingPanel
from vibephoto.ui.curve_editor import ToneCurveEditor
from vibephoto.ui.histogram import HistogramWidget
from vibephoto.ui.layers_panel import LayersPanel
from vibephoto.ui.lens_panel import LensProfilePanel
from vibephoto.ui.mask_panel import MaskPanel
from vibephoto.ui.preset_browser import PresetBrowser
from vibephoto.ui.white_balance_panel import WhiteBalancePanel

# Edit complexity levels: how much of the panel shows.
SIMPLE, INTERMEDIATE, ADVANCED = 0, 1, 2
MODE_NAMES = ("Simple", "Intermediate", "Advanced")


def _make_panel_compact(root: QWidget) -> None:
    """Let wide controls shrink to the panel width so nothing clips horizontally.

    Comboboxes size to their longest item and buttons to their text, which can
    force the scroll body wider than its viewport and clip the right edge (the
    panel has no horizontal scrollbar). Relaxing those minimums lets the column
    always fit, shrinking the controls instead of overflowing.
    """
    for combo in root.findChildren(QComboBox):
        combo.setMinimumWidth(0)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(3)
    for button in root.findChildren(QPushButton):
        button.setMinimumWidth(0)
        policy = button.sizePolicy()
        policy.setHorizontalPolicy(QSizePolicy.Policy.Preferred)
        button.setSizePolicy(policy)
    for check in root.findChildren(QCheckBox):
        check.setMinimumWidth(0)


@dataclass(frozen=True)
class SliderSpec:
    """One slider: which EditState field it drives, its range, and its level."""

    param: str
    label: str
    minimum: float
    maximum: float
    default: float
    mult: int = 1  # integer steps per unit (precision for fractional ranges)
    subkey: str | None = None  # for dict params (hsl_hue/sat/lum)
    level: int = SIMPLE  # lowest edit mode at which this slider appears
    raw_only: bool = False  # only shown for RAW (scene-linear) photos
    step: float = 1.0  # one -/+ stepper-button nudge, in value units

    @property
    def ident(self) -> tuple[str, str | None]:
        return (self.param, self.subkey)


def _hsl_specs(param: str) -> list[SliderSpec]:
    return [
        SliderSpec(param, band.capitalize(), -100, 100, 0, subkey=band, level=INTERMEDIATE)
        for band in HSL_BANDS
    ]


# Groups: (title, specs, expanded_by_default, group_level).
PARAM_GROUPS: tuple[tuple[str, list[SliderSpec], bool, int], ...] = (
    (
        "Basic",
        [
            SliderSpec("temp", "Temperature", -100, 100, 0),
            SliderSpec("tint", "Tint", -100, 100, 0),
            SliderSpec("exposure", "Exposure", -5, 5, 0, mult=100, step=0.05),
            SliderSpec("contrast", "Contrast", -100, 100, 0),
            SliderSpec("highlights", "Highlights", -100, 100, 0),
            SliderSpec("shadows", "Shadows", -100, 100, 0),
            SliderSpec("whites", "Whites", -100, 100, 0),
            SliderSpec("blacks", "Blacks", -100, 100, 0),
            SliderSpec("highlight_recovery", "Highlight Recovery", 0, 100, 0,
                       level=INTERMEDIATE, raw_only=True),
            SliderSpec("texture", "Texture", -100, 100, 0, level=INTERMEDIATE),
            SliderSpec("clarity", "Clarity", -100, 100, 0, level=INTERMEDIATE),
            SliderSpec("dehaze", "Dehaze", -100, 100, 0, level=INTERMEDIATE),
            SliderSpec("vibrance", "Vibrance", -100, 100, 0),
            SliderSpec("saturation", "Saturation", -100, 100, 0),
        ],
        True,
        SIMPLE,
    ),
    ("HSL — Hue", _hsl_specs("hsl_hue"), False, INTERMEDIATE),
    ("HSL — Saturation", _hsl_specs("hsl_sat"), False, INTERMEDIATE),
    ("HSL — Luminance", _hsl_specs("hsl_lum"), False, INTERMEDIATE),
    (
        "Detail",
        [
            SliderSpec("sharpen_amount", "Sharpening", 0, 150, 0, level=INTERMEDIATE),
            SliderSpec("sharpen_radius", "Radius", 0.5, 3, 1, mult=10, step=0.1, level=ADVANCED),
            SliderSpec("sharpen_detail", "Detail", 0, 100, 25, level=ADVANCED),
            SliderSpec("sharpen_masking", "Masking", 0, 100, 0, level=ADVANCED),
            SliderSpec("noise_luminance", "Luminance NR", 0, 100, 0, level=INTERMEDIATE),
            SliderSpec("noise_color", "Color NR", 0, 100, 0, level=INTERMEDIATE),
        ],
        False,
        INTERMEDIATE,
    ),
    (
        "Lens Corrections",
        [
            SliderSpec("lens_distortion", "Distortion", -100, 100, 0, level=INTERMEDIATE),
            SliderSpec("lens_ca", "Defringe (CA)", -100, 100, 0, level=INTERMEDIATE),
            SliderSpec("lens_vignetting", "Vignetting", -100, 100, 0, level=INTERMEDIATE),
        ],
        False,
        INTERMEDIATE,
    ),
    (
        "Effects",
        [
            SliderSpec("vignette_amount", "Vignette", -100, 100, 0),
            SliderSpec("vignette_midpoint", "Midpoint", 0, 100, 50),
            SliderSpec("grain_amount", "Grain", 0, 100, 0),
        ],
        False,
        ADVANCED,
    ),
)


class _ResetSlider(QSlider):
    """A horizontal slider that emits :attr:`doubleClicked` (to reset to default)."""

    doubleClicked = Signal()

    def __init__(self) -> None:
        super().__init__(Qt.Orientation.Horizontal)
        # Don't grab focus by wheel/tab, so scrolling never lands on a slider.
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

    def mouseDoubleClickEvent(self, event: object) -> None:
        self.doubleClicked.emit()

    def wheelEvent(self, event: QWheelEvent) -> None:
        # Ignore the wheel so it scrolls the panel instead of nudging the value;
        # the slider only moves when dragged/clicked.
        event.ignore()


class _SliderRow(QWidget):
    """A labelled slider bound to one :class:`SliderSpec`."""

    changed = Signal(object, object, float)  # param, subkey, value

    def __init__(self, spec: SliderSpec, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._spec = spec
        layout = QGridLayout(self)
        layout.setContentsMargins(2, 1, 2, 1)
        layout.setColumnStretch(1, 1)

        name = QLabel(spec.label)
        name.setStyleSheet("color:#c9ccd1; font-size:12px;")
        self._value = QLabel(self._format(spec.default))
        self._value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._value.setStyleSheet("color:#9a9da3; font-size:12px;")
        self._value.setMinimumWidth(44)

        self._slider = _ResetSlider()
        self._slider.setMinimum(int(spec.minimum * spec.mult))
        self._slider.setMaximum(int(spec.maximum * spec.mult))
        self._slider.setValue(int(spec.default * spec.mult))
        # Keyboard ←/→ on a focused slider nudge by one step, matching the buttons.
        self._slider.setSingleStep(max(1, round(spec.step * spec.mult)))
        self._slider.valueChanged.connect(self._on_change)
        self._slider.doubleClicked.connect(self.reset)

        # -/+ stepper buttons: one click = one step (click twice for +2),
        # Shift+click = x5. An extra workflow on top of the slider drag.
        self._dec = self._make_stepper("‹", -1)  # noqa: RUF001 (chevron glyph)
        self._inc = self._make_stepper("›", +1)  # noqa: RUF001 (chevron glyph)

        layout.addWidget(name, 0, 0)
        layout.addWidget(self._value, 0, 2)
        layout.addWidget(self._dec, 1, 0)
        layout.addWidget(self._slider, 1, 1)
        layout.addWidget(self._inc, 1, 2)

    def _make_stepper(self, glyph: str, direction: int) -> QToolButton:
        button = QToolButton()
        button.setText(glyph)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # never steal scroll/tab focus
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setAutoRepeat(True)  # hold to keep stepping
        button.setFixedSize(26, 22)
        button.setToolTip(f"Step {'down' if direction < 0 else 'up'} (Shift = x5)")
        # Bigger, brighter, with a visible chip so the arrows are easy to spot/hit.
        button.setStyleSheet(
            "QToolButton{color:#e6e8eb; font-size:19px; font-weight:700;"
            "border:1px solid #3a3d42; border-radius:4px; padding:0; background:#2a2d31;}"
            "QToolButton:hover{color:#ffffff; background:#3d8bfd; border-color:#3d8bfd;}"
            "QToolButton:pressed{background:#2d6cdf;}"
        )
        button.clicked.connect(lambda: self._nudge(direction))
        return button

    def _nudge(self, direction: int) -> None:
        """Move the value by one step (x5 with Shift held), clamped to the range."""
        shift = QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier
        delta = direction * self._spec.step * (5 if shift else 1)
        current = self._slider.value() / self._spec.mult
        target = min(self._spec.maximum, max(self._spec.minimum, current + delta))
        self.set_value(target)
        self.changed.emit(self._spec.param, self._spec.subkey, target)

    def _format(self, value: float) -> str:
        return f"{value:.2f}" if self._spec.mult >= 100 else f"{value:.0f}"

    def _on_change(self, raw: int) -> None:
        value = raw / self._spec.mult
        self._value.setText(self._format(value))
        self.changed.emit(self._spec.param, self._spec.subkey, value)

    def set_value(self, value: float) -> None:
        """Set the slider without emitting (used when syncing to an EditState)."""
        self._slider.blockSignals(True)
        self._slider.setValue(round(value * self._spec.mult))
        self._value.setText(self._format(value))
        self._slider.blockSignals(False)

    def reset(self) -> None:
        self.set_value(self._spec.default)
        self.changed.emit(self._spec.param, self._spec.subkey, self._spec.default)

    @property
    def level(self) -> int:
        return self._spec.level

    @property
    def raw_only(self) -> bool:
        return self._spec.raw_only


class _CollapsibleSection(QWidget):
    """A titled section whose body can be collapsed, like the conventional panels."""

    def __init__(self, title: str, *, expanded: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._header = QToolButton()
        self._header.setText(title.upper())
        self._header.setCheckable(True)
        self._header.setChecked(expanded)
        self._header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._header.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.setStyleSheet(
            "QToolButton{color:#8a8d93; font-size:11px; font-weight:600; letter-spacing:1px;"
            "border:none; padding:8px 2px 4px 2px; background:transparent;}"
            "QToolButton:hover{color:#c9ccd1;}"
        )
        self._header.clicked.connect(self._toggle)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 6)
        self._body_layout.setSpacing(2)
        self._body.setVisible(expanded)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._header)
        layout.addWidget(self._body)

    def add_row(self, widget: QWidget) -> None:
        self._body_layout.addWidget(widget)

    def _toggle(self) -> None:
        visible = self._header.isChecked()
        self._body.setVisible(visible)
        self._header.setArrowType(
            Qt.ArrowType.DownArrow if visible else Qt.ArrowType.RightArrow
        )


class AdjustmentsPanel(QWidget):
    """Histogram, Auto buttons, preset combos, sliders, and a Copy/Paste footer."""

    param_changed = Signal(object, object, float)  # param, subkey, value
    curve_changed = Signal(str, object)  # EditState curve field, list[(int, int)]
    wb_picker_toggled = Signal(bool)  # White Balance Selector armed/disarmed
    wb_auto_requested = Signal()
    wb_as_shot_requested = Signal()
    bw_toggled = Signal(bool)
    reset_requested = Signal()
    preset_chosen = Signal(str, object)  # name, EditState (from the preset combo)
    add_preset_requested = Signal()
    auto_edit_requested = Signal()
    auto_hdr_requested = Signal()
    copy_requested = Signal()
    paste_requested = Signal()
    layer_selected = Signal(int)
    layer_added = Signal()
    layer_removed = Signal()
    layer_toggled = Signal(int, bool)
    masks_changed = Signal(object)  # list[Mask] for the active layer
    profile_chosen = Signal(str)  # creative/camera base look
    lens_profile_chosen = Signal(str)  # lens-correction profile name
    lens_auto_requested = Signal()  # detect lens from EXIF + apply
    lens_profile_save_requested = Signal(str)  # save current amounts as a profile
    lens_profile_delete_requested = Signal(str)  # delete a custom profile

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # The floor fits the widest controls so nothing clips; the ceiling is
        # generous so the drag-grip can widen the panel (resizable UI).
        self.setMinimumWidth(350)
        self.setMaximumWidth(760)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        body = QWidget()
        outer = QVBoxLayout(body)
        outer.setContentsMargins(10, 8, 10, 6)
        outer.setSpacing(4)

        # Edit-complexity selector: Simple / Intermediate / Advanced shows
        # progressively more sliders and sections.
        self._mode = INTERMEDIATE
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        mode_bar = QHBoxLayout()
        mode_bar.setSpacing(0)
        for level, name in enumerate(MODE_NAMES):
            button = QPushButton(name)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(f"{name} edits — show {('fewer', 'more', 'all')[level]} controls")
            button.setStyleSheet(
                "QPushButton{color:#9a9da3; background:#202225; border:1px solid #3a3d42;"
                "padding:3px 0; font-size:11px;}"
                "QPushButton:checked{color:#f0f0f0; background:#2d6cdf; border-color:#2d6cdf;}"
            )
            self._mode_group.addButton(button, level)
            mode_bar.addWidget(button)
        self._mode_group.button(INTERMEDIATE).setChecked(True)
        self._mode_group.idClicked.connect(self.set_mode)
        outer.addLayout(mode_bar)

        self._histogram = HistogramWidget()
        outer.addWidget(self._histogram)

        # Auto Edit / Auto HDR — one-click adaptive adjustments.
        auto = QHBoxLayout()
        auto_edit = QPushButton("Auto Edit")
        auto_edit.setToolTip("Analyse this photo and set tone automatically")
        auto_edit.clicked.connect(self.auto_edit_requested.emit)
        auto_hdr = QPushButton("Auto HDR")
        auto_hdr.setToolTip("Apply a single-image HDR tone-map")
        auto_hdr.clicked.connect(self.auto_hdr_requested.emit)
        for button in (auto_edit, auto_hdr):
            button.setStyleSheet("font-weight:600;")
            auto.addWidget(button)
        outer.addLayout(auto)

        # Creative/camera profile — the base look beneath the adjustments.
        profile_row = QHBoxLayout()
        profile_label = QLabel("Profile")
        profile_label.setStyleSheet("color:#c9ccd1; font-size:12px;")
        self._profile = QComboBox()
        self._profile.addItems(PROFILE_NAMES)
        self._profile.currentTextChanged.connect(self.profile_chosen.emit)
        profile_row.addWidget(profile_label)
        profile_row.addWidget(self._profile, 1)
        outer.addLayout(profile_row)

        # Preset combos (folder + preset, with hover preview).
        self.preset_browser = PresetBrowser()
        self.preset_browser.preset_chosen.connect(self.preset_chosen.emit)
        self.preset_browser.add_requested.connect(self.add_preset_requested.emit)
        outer.addWidget(self.preset_browser)

        # Edit layers (below the presets).
        self.layers_panel = LayersPanel()
        self.layers_panel.layer_selected.connect(self.layer_selected.emit)
        self.layers_panel.layer_added.connect(self.layer_added.emit)
        self.layers_panel.layer_removed.connect(self.layer_removed.emit)
        self.layers_panel.layer_toggled.connect(self.layer_toggled.emit)
        outer.addWidget(self.layers_panel)

        actions = QHBoxLayout()
        reset_btn = QPushButton("Reset All")
        reset_btn.clicked.connect(self.reset_requested.emit)
        self._bw = QCheckBox("Black && White")
        self._bw.setStyleSheet("color:#c9ccd1; padding:2px 0;")
        self._bw.toggled.connect(self.bw_toggled.emit)
        actions.addWidget(self._bw, 1)
        actions.addWidget(reset_btn)
        outer.addLayout(actions)

        self._rows: dict[tuple[str, str | None], _SliderRow] = {}
        self._sections: list[tuple[_CollapsibleSection, int, list[_SliderRow]]] = []
        self._is_raw = False
        # White balance (RAW): a dedicated Kelvin Temp/Tint panel with eyedropper.
        self.white_balance = WhiteBalancePanel()
        self.white_balance.param_changed.connect(self.param_changed.emit)
        self.white_balance.picker_toggled.connect(self.wb_picker_toggled.emit)
        self.white_balance.auto_requested.connect(self.wb_auto_requested.emit)
        self.white_balance.as_shot_requested.connect(self.wb_as_shot_requested.emit)
        # Interactive graph widgets — a tone curve and colour-grading wheels.
        self.curve_editor = ToneCurveEditor()
        self.curve_editor.curve_changed.connect(self.curve_changed.emit)
        self.grade_panel = ColorGradingPanel()
        self.grade_panel.param_changed.connect(self.param_changed.emit)
        # Masks (per-layer local adjustments).
        self.mask_panel = MaskPanel()
        self.mask_panel.masks_changed.connect(self.masks_changed.emit)
        # Lens profile (auto-fix + presets), above the manual lens sliders.
        self.lens_panel = LensProfilePanel()
        self.lens_panel.profile_chosen.connect(self.lens_profile_chosen.emit)
        self.lens_panel.auto_requested.connect(self.lens_auto_requested.emit)
        self.lens_panel.save_requested.connect(self.lens_profile_save_requested.emit)
        self.lens_panel.delete_requested.connect(self.lens_profile_delete_requested.emit)

        groups = {group[0]: group for group in PARAM_GROUPS}
        # a familiar, professional order, interleaving the graph sections with the sliders.
        # Crop & straighten is the on-canvas free crop tool (footer ⌗ / R / T), not a panel.
        self._add_widget_section(outer, "Masks", self.mask_panel, INTERMEDIATE)
        self._wb_section = self._add_widget_section(
            outer, "White Balance", self.white_balance, SIMPLE, expanded=True
        )
        self._add_slider_section(outer, groups["Basic"])
        self._add_widget_section(outer, "Tone Curve", self.curve_editor, INTERMEDIATE)
        for title in ("HSL — Hue", "HSL — Saturation", "HSL — Luminance"):
            self._add_slider_section(outer, groups[title])
        self._add_widget_section(outer, "Color Grading", self.grade_panel, INTERMEDIATE)
        self._add_slider_section(outer, groups["Detail"])
        self._add_widget_section(outer, "Lens Profile", self.lens_panel, INTERMEDIATE)
        self._add_slider_section(outer, groups["Lens Corrections"])
        self._add_slider_section(outer, groups["Effects"])
        outer.addStretch(1)
        _make_panel_compact(body)  # let wide combos/buttons shrink so nothing clips
        scroll.setWidget(body)
        self.set_mode(self._mode)

        # Fixed footer: Copy / Paste develop settings.
        footer = QHBoxLayout()
        footer.setContentsMargins(10, 6, 10, 8)
        copy_btn = QPushButton("Copy Settings")
        copy_btn.clicked.connect(self.copy_requested.emit)
        paste_btn = QPushButton("Paste Settings")
        paste_btn.setToolTip("Paste copied settings (hold Shift to paste to all selected)")
        paste_btn.clicked.connect(self.paste_requested.emit)
        footer.addWidget(copy_btn)
        footer.addWidget(paste_btn)
        footer_widget = QWidget()
        footer_widget.setLayout(footer)
        footer_widget.setStyleSheet("background:#202225; border-top:1px solid #3a3d42;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(scroll, 1)
        layout.addWidget(footer_widget)

    def _add_slider_section(
        self, outer: QVBoxLayout, group: tuple[str, list[SliderSpec], bool, int]
    ) -> None:
        title, specs, expanded, group_level = group
        section = _CollapsibleSection(title, expanded=expanded)
        rows: list[_SliderRow] = []
        for spec in specs:
            row = _SliderRow(spec)
            row.changed.connect(self.param_changed.emit)
            self._rows[spec.ident] = row
            section.add_row(row)
            rows.append(row)
        outer.addWidget(section)
        self._sections.append((section, group_level, rows))

    def _add_widget_section(
        self, outer: QVBoxLayout, title: str, widget: QWidget, level: int,
        *, expanded: bool = False,
    ) -> _CollapsibleSection:
        """Add a collapsible section wrapping a custom widget (no slider rows)."""
        section = _CollapsibleSection(title, expanded=expanded)
        section.add_row(widget)
        outer.addWidget(section)
        self._sections.append((section, level, []))
        return section

    def update_histogram(self, rgb: NDArray[np.uint8]) -> None:
        self._histogram.set_image(rgb)

    def clear_histogram(self) -> None:
        self._histogram.clear()

    def set_layers(self, stack: LayerStack) -> None:
        self.layers_panel.set_stack(stack)

    def set_mode(self, mode: int) -> None:
        """Show only the sliders/sections at or below the chosen complexity level."""
        self._mode = mode
        button = self._mode_group.button(mode)
        if button is not None and not button.isChecked():
            button.setChecked(True)
        for section, group_level, rows in self._sections:
            visible_rows = 0
            for row in rows:
                show = group_level <= mode and row.level <= mode
                row.setVisible(show)
                visible_rows += int(show)
            # Slider sections hide when the mode leaves them empty; widget sections
            # (no rows — e.g. the curve / grade graphs) show by their own level.
            has_content = visible_rows > 0 if rows else group_level <= mode
            section.setVisible(group_level <= mode and has_content)
        self._apply_wb_visibility()

    def set_raw_mode(self, is_raw: bool) -> None:
        """Show the Kelvin WB panel for RAW (and hide the relative Temp/Tint sliders)."""
        self._is_raw = is_raw
        self._apply_wb_visibility()

    def _apply_wb_visibility(self) -> None:
        # RAW: white balance lives in the dedicated Kelvin panel, so the relative
        # Temperature/Tint sliders are hidden; RAW-only sliders (Highlight Recovery)
        # appear. The reverse holds for JPEGs. Edit-mode level still applies.
        self._wb_section.setVisible(self._is_raw)
        for (param, _subkey), row in self._rows.items():
            if row.raw_only:
                row.setVisible(self._is_raw and row.level <= self._mode)
            elif param in ("temp", "tint"):
                row.setVisible(not self._is_raw and row.level <= self._mode)

    def set_state(self, state: EditState) -> None:
        """Sync every control to ``state`` without emitting change signals."""
        self._bw.blockSignals(True)
        self._bw.setChecked(state.grayscale)
        self._bw.blockSignals(False)
        self._profile.blockSignals(True)
        self._profile.setCurrentText(state.profile)
        self._profile.blockSignals(False)
        for (param, subkey), row in self._rows.items():
            attr = getattr(state, param)
            value = attr[subkey] if subkey is not None else attr
            row.set_value(float(value))
        self.white_balance.set_values(state.wb_kelvin, state.wb_tint)
        self.curve_editor.set_state(state)
        self.grade_panel.set_state(state)
