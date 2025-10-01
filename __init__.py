from .nodes import MaskToCenterPoint, MaskSubMassDetector

# ComfyUI Registration
NODE_CLASS_MAPPINGS = {
    "MaskToCenterPoint": MaskToCenterPoint,
    "MaskSubMassDetector": MaskSubMassDetector,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MaskToCenterPoint": "Mask to Center Point",
    "MaskSubMassDetector": "Detect Mask Sub-Masses",
}

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']

