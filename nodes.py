import torch
import numpy as np
from scipy.ndimage import center_of_mass, label, binary_opening
import json

# --- Node 1: Mask to Center Point (Simple Modes) ---

class MaskToCenterPoint:
    """
    Finds the center of masks. Can find a single center for a combined mask/segs,
    or find the center of each physically separate (disconnected) region.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mode": (["Combined", "Separate Regions"],),
                "min_area": ("INT", {"default": 0, "min": 0, "max": 99999, "step": 1}),
            },
            "optional": {
                "mask": ("MASK",),
                "segs": ("SEGS",),
            }
        }

    RETURN_TYPES = ("STRING", "INT", "INT", "STRING",)
    RETURN_NAMES = ("coordinates", "x", "y", "debug",)
    FUNCTION = "process_inputs"
    CATEGORY = "Masquerade Mods"

    def process_inputs(self, mode: str, min_area: int, mask=None, segs=None):
        if mask is None and segs is None:
            return ("[]", 0, 0, "No mask or segs provided.")
        
        coords_list, debug_lines = [], []
        
        process_individually = mode == "Separate Regions"

        if segs is not None:
            if not (isinstance(segs, tuple) and len(segs) == 2 and isinstance(segs[1], list)):
                print("Warning: SEGS input has an unexpected format.")
                return ("[]", 0, 0, "Error: Invalid SEGS format.")
            
            seg_list = segs[1]
            debug_lines.append(f"Processing {len(seg_list)} segment(s) in '{mode}' mode.")

            if not process_individually: # Combined mode
                combined_mask_np = self.combine_segs_to_mask(seg_list)
                if combined_mask_np is not None:
                    self.calculate_centers(combined_mask_np, "Combined mask", "Combined", coords_list, debug_lines, min_area=min_area)
            else: # Separate Regions mode
                for i, seg_object in enumerate(seg_list):
                    try:
                        cropped_mask_data = seg_object.cropped_mask
                        cropped_mask_np = cropped_mask_data.cpu().numpy().squeeze() if isinstance(cropped_mask_data, torch.Tensor) else np.squeeze(cropped_mask_data)
                        crop_x, crop_y = seg_object.crop_region[:2]
                        self.calculate_centers(cropped_mask_np, f"Segment {i}", "Separate Regions", coords_list, debug_lines, min_area=min_area, offset_x=crop_x, offset_y=crop_y)
                    except (AttributeError, IndexError, TypeError) as e:
                        print(f"Warning: Skipping segment {i} due to unexpected data structure. Error: {e}")
        
        elif mask is not None:
            debug_lines.append(f"Processing {mask.shape[0]} mask(s) in '{mode}' mode.")
            for b in range(mask.shape[0]):
                mask_np = mask[b].cpu().numpy()
                self.calculate_centers(mask_np, f"Mask {b}", mode, coords_list, debug_lines, min_area=min_area)

        output_string = json.dumps(coords_list)
        first_x = coords_list[0]['x'] if coords_list else 0
        first_y = coords_list[0]['y'] if coords_list else 0
        summary = f"Total center points found: {len(coords_list)}."
        debug_lines.insert(0, summary)
        debug_string = "\n".join(debug_lines)
        
        return (output_string, first_x, first_y, debug_string,)

    def combine_segs_to_mask(self, seg_list):
        if not seg_list: return None
        max_w, max_h = 0, 0
        for seg_object in seg_list:
            try:
                x, y, w, h = seg_object.crop_region
                max_w, max_h = max(max_w, x + w), max(max_h, y + h)
            except (AttributeError, IndexError, TypeError): continue
        if max_w == 0 or max_h == 0: return None

        combined_mask_np = np.zeros((max_h, max_w), dtype=np.float32)
        for i, seg_object in enumerate(seg_list):
            try:
                cropped_mask_data = seg_object.cropped_mask
                cropped_mask_np = cropped_mask_data.cpu().numpy().squeeze() if isinstance(cropped_mask_data, torch.Tensor) else np.squeeze(cropped_mask_data)
                x, y = seg_object.crop_region[:2]
                h, w = cropped_mask_np.shape
                view = combined_mask_np[y:y+h, x:x+w]
                np.maximum(view, cropped_mask_np, out=view)
            except (AttributeError, IndexError, TypeError, ValueError) as e:
                print(f"Warning: Skipping segment {i} during combination due to an error: {e}")
        return combined_mask_np

    def calculate_centers(self, mask_np, name, mode, coords_list, debug_lines, min_area=0, offset_x=0, offset_y=0):
        if np.count_nonzero(mask_np) == 0:
            return

        if mode == "Separate Regions":
            labeled_array, num_features = label(mask_np)
            if num_features > 0:
                debug_lines.append(f"- {name}: found {num_features} separate region(s).")
                centers = center_of_mass(mask_np, labeled_array, range(1, num_features + 1))
                if num_features == 1:
                    centers = [centers] # Ensure it's always a list to iterate
                for i, (center_y, center_x) in enumerate(centers):
                    region_mask = (labeled_array == (i + 1))
                    region_area = np.count_nonzero(mask_np[region_mask])
                    if region_area >= min_area:
                        x_coord, y_coord = int(round(center_x + offset_x)), int(round(center_y + offset_y))
                        coords_list.append({"x": x_coord, "y": y_coord})
                        debug_lines.append(f"  - Region {i}: area={region_area}, center=({x_coord}, {y_coord})")
                    else:
                        debug_lines.append(f"  - Region {i}: area={region_area}, skipped (min area: {min_area}).")

        else: # Combined mode
            area = np.count_nonzero(mask_np)
            if area >= min_area:
                center_y, center_x = center_of_mass(mask_np)
                x_coord, y_coord = int(round(center_x + offset_x)), int(round(center_y + offset_y))
                coords_list.append({"x": x_coord, "y": y_coord})
                debug_lines.append(f"- {name}: area={area}, center=({x_coord}, {y_coord})")
            else:
                debug_lines.append(f"- {name}: area={area}, skipped (min area: {min_area}).")


# --- Node 2: Detect Mask Sub-Masses ---

class MaskSubMassDetector:
    """
    Detects the centers of dense areas (sub-masses) within a single connected mask
    by using morphological opening to sever narrow connections.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "separation_strength": ("INT", {"default": 5, "min": 1, "max": 50, "step": 1}),
            },
            "optional": {
                "mask": ("MASK",),
                "segs": ("SEGS",),
            }
        }

    RETURN_TYPES = ("STRING", "INT", "INT", "STRING",)
    RETURN_NAMES = ("coordinates", "x", "y", "debug",)
    FUNCTION = "detect_centers"
    CATEGORY = "Masquerade Mods"

    def detect_centers(self, separation_strength: int, mask=None, segs=None):
        if mask is None and segs is None:
            return ("[]", 0, 0, "No mask or segs provided.")
        
        coords_list, debug_lines = [], []

        if segs is not None:
            if not (isinstance(segs, tuple) and len(segs) == 2 and isinstance(segs[1], list)):
                print("Warning: SEGS input has an unexpected format.")
                return ("[]", 0, 0, "Error: Invalid SEGS format.")
            
            seg_list = segs[1]
            debug_lines.append(f"Processing {len(seg_list)} segment(s) to detect sub-masses.")

            for i, seg_object in enumerate(seg_list):
                try:
                    cropped_mask_data = seg_object.cropped_mask
                    cropped_mask_np = cropped_mask_data.cpu().numpy().squeeze() if isinstance(cropped_mask_data, torch.Tensor) else np.squeeze(cropped_mask_data)
                    crop_x, crop_y = seg_object.crop_region[:2]
                    self.calculate_submass_centers(cropped_mask_np, f"Segment {i}", separation_strength, coords_list, debug_lines, offset_x=crop_x, offset_y=crop_y)
                except (AttributeError, IndexError, TypeError) as e:
                    print(f"Warning: Skipping segment {i} due to unexpected data structure. Error: {e}")
        
        elif mask is not None:
            debug_lines.append(f"Processing {mask.shape[0]} mask(s) to detect sub-masses.")
            for b in range(mask.shape[0]):
                mask_np = mask[b].cpu().numpy()
                if np.count_nonzero(mask_np) == 0: continue
                self.calculate_submass_centers(mask_np, f"Mask {b}", separation_strength, coords_list, debug_lines)

        output_string = json.dumps(coords_list)
        first_x = coords_list[0]['x'] if coords_list else 0
        first_y = coords_list[0]['y'] if coords_list else 0
        summary = f"Total center points found: {len(coords_list)}."
        debug_lines.insert(0, summary)
        debug_string = "\n".join(debug_lines)
        
        return (output_string, first_x, first_y, debug_string,)

    def calculate_submass_centers(self, mask_np, name, strength, coords_list, debug_lines, offset_x=0, offset_y=0):
        binary_mask = mask_np > 0.5
        
        # Create a disk-shaped structuring element. The 'strength' is its radius.
        # This is more aggressive and intuitive than using iterations.
        radius = strength
        y, x = np.ogrid[-radius:radius+1, -radius:radius+1]
        structure = x**2 + y**2 <= radius**2
        
        # Perform a single, powerful opening operation.
        opened_mask = binary_opening(binary_mask, structure=structure, iterations=1)
        
        labeled_array, num_features = label(opened_mask)
        
        if num_features > 0:
            debug_lines.append(f"- {name}: detected {num_features} sub-mass(es) with strength {strength}.")
            for i in range(1, num_features + 1):
                # Use the label to select the region from the ORIGINAL mask for accurate center of mass.
                component_mask = np.where(labeled_array == i, mask_np, 0)
                area = np.count_nonzero(component_mask)
                if area > 0:
                    center_y, center_x = center_of_mass(component_mask)
                    x_coord, y_coord = int(round(center_x + offset_x)), int(round(center_y + offset_y))
                    coords_list.append({"x": x_coord, "y": y_coord})
                    debug_lines.append(f"  - Sub-mass {i-1}: area={area}, center=({x_coord}, {y_coord})")

