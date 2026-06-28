"""Edit layers — a stack of non-destructive adjustment layers.

A photo's edit is an ordered :class:`LayerStack`: each :class:`EditLayer` holds its
own :class:`EditState` and is applied on top of the result of the layer below it.
This lets a photographer, say, Auto-Edit one layer and drop a preset on another —
the looks compose instead of overwriting. One layer (``"Base"``) always exists.
The stack serialises to JSON and reads back older single-:class:`EditState` saves
transparently (they load as a one-layer stack).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from vibephoto.processing.edit_state import EditState
from vibephoto.processing.geometry import Geometry
from vibephoto.processing.mask import Mask


@dataclass
class EditLayer:
    """One adjustment layer: a name, its edit, an optional local mask, and on/off.

    ``masks`` make the layer *local*: when present, the layer's developed pixels are
    blended back over its input by the combined mask coverage, so the edit applies
    only inside the mask. Empty = a global layer (the original behaviour).
    """

    name: str
    state: EditState = field(default_factory=EditState)
    enabled: bool = True
    masks: list[Mask] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "state": self.state.to_dict(),
            "masks": [mask.to_dict() for mask in self.masks],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EditLayer:
        raw_masks = data.get("masks", [])
        masks = [Mask.from_dict(m) for m in raw_masks] if isinstance(raw_masks, list) else []
        return cls(
            name=str(data.get("name", "Layer")),
            state=EditState.from_dict(data.get("state", {})),
            enabled=bool(data.get("enabled", True)),
            masks=masks,
        )

    def copy(self) -> EditLayer:
        return EditLayer(self.name, self.state.copy(), self.enabled, [m.copy() for m in self.masks])


@dataclass
class LayerStack:
    """An ordered stack of :class:`EditLayer`, applied bottom-to-top.

    ``geometry`` (crop + straighten) is photo-level: applied to the base image once,
    before any layer develops it.
    """

    layers: list[EditLayer] = field(default_factory=lambda: [EditLayer("Base")])
    active: int = 0
    geometry: Geometry = field(default_factory=Geometry)

    @classmethod
    def single(cls, state: EditState | None = None) -> LayerStack:
        """A one-layer stack (the default edit, or wrapping an existing state)."""
        return cls([EditLayer("Base", state.copy() if state is not None else EditState())], 0)

    @property
    def active_layer(self) -> EditLayer:
        self.active = max(0, min(self.active, len(self.layers) - 1))
        return self.layers[self.active]

    @property
    def active_state(self) -> EditState:
        return self.active_layer.state

    def add_layer(self, name: str | None = None) -> EditLayer:
        """Append a new empty layer and make it active."""
        layer = EditLayer(name or f"Layer {len(self.layers) + 1}")
        self.layers.append(layer)
        self.active = len(self.layers) - 1
        return layer

    def remove_active(self) -> None:
        """Delete the active layer (the last remaining layer is kept)."""
        if len(self.layers) > 1:
            del self.layers[self.active]
            self.active = max(0, min(self.active, len(self.layers) - 1))

    def is_identity(self) -> bool:
        """True when the stack is a single, unedited, enabled base layer (and uncropped)."""
        return (
            len(self.layers) == 1
            and self.layers[0].enabled
            and self.layers[0].state.is_identity()
            and self.geometry.is_identity()
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "layers": [layer.to_dict() for layer in self.layers],
            "active": self.active,
            "geometry": self.geometry.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LayerStack:
        raw = data.get("layers")
        if isinstance(raw, list) and raw:
            return cls(
                [EditLayer.from_dict(item) for item in raw],
                int(data.get("active", 0)),
                Geometry.from_dict(data.get("geometry", {})),
            )
        # Backward compatibility: a bare EditState dict becomes a single layer.
        return cls.single(EditState.from_dict(data))

    def copy(self) -> LayerStack:
        return LayerStack(
            [layer.copy() for layer in self.layers], self.active, self.geometry.copy()
        )
