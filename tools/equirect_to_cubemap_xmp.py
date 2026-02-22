#!/usr/bin/env python3
"""Split equirectangular images (and optional masks) into cubemap faces + XMP rig sidecars.

Designed for RealityCapture/RealityScan workflows:
- 1 equirectangular frame -> 6 perspective cubemap faces.
- Per-face XMP sidecars that lock camera pose/calibration and bind faces into one rig.
- Optional mask splitting with RealityCapture-compatible mask naming.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import uuid

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


def require_runtime_dependencies():
    try:
        import numpy as np  # type: ignore
        from PIL import Image  # type: ignore
    except ModuleNotFoundError as exc:
        missing = exc.name or "required package"
        raise SystemExit(
            f"Missing dependency: {missing}. Install with: python3 -m pip install numpy pillow"
        ) from exc

    return np, Image


def build_face_specs(np):
    return {
        "front": {"forward": np.array([0.0, 0.0, 1.0]), "up": np.array([0.0, 1.0, 0.0])},
        "right": {"forward": np.array([1.0, 0.0, 0.0]), "up": np.array([0.0, 1.0, 0.0])},
        "back": {"forward": np.array([0.0, 0.0, -1.0]), "up": np.array([0.0, 1.0, 0.0])},
        "left": {"forward": np.array([-1.0, 0.0, 0.0]), "up": np.array([0.0, 1.0, 0.0])},
        "up": {"forward": np.array([0.0, 1.0, 0.0]), "up": np.array([0.0, 0.0, -1.0])},
        "down": {"forward": np.array([0.0, -1.0, 0.0]), "up": np.array([0.0, 0.0, 1.0])},
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Split one image or a whole folder of equirectangular images into cubemap faces, "
            "write XMP rig sidecars, and optionally split matching mask images."
        )
    )
    parser.add_argument("input", type=Path, help="Input image file or directory")
    parser.add_argument("output_dir", type=Path, help="Output directory")
    parser.add_argument("--face-size", type=int, default=1536, help="Cubemap face size in pixels")
    parser.add_argument(
        "--image-format",
        choices=["png", "jpg"],
        default="png",
        help="Output image format",
    )
    parser.add_argument("--jpg-quality", type=int, default=98, help="JPEG quality for face images")
    parser.add_argument(
        "--xmp-namespace",
        default="http://www.capturingreality.com/ns/xcr/1.1#",
        help="XMP namespace URI for xcr tags",
    )
    parser.add_argument(
        "--with-masks",
        action="store_true",
        help="Also locate/split mask images paired with each source image",
    )
    parser.add_argument(
        "--input-mask-suffix",
        default="_mask",
        help=(
            "Mask suffix for input mask lookup. Ex: frame_0001.png -> frame_0001_mask.png. "
            "Also auto-tries RealityCapture style: frame_0001.png.mask.png"
        ),
    )
    parser.add_argument(
        "--output-mask-mode",
        choices=["dot-mask", "suffix"],
        default="dot-mask",
        help=(
            "Output mask filename mode: 'dot-mask' => image.ext.mask.png (RC style), "
            "'suffix' => image_stem_mask.png"
        ),
    )
    parser.add_argument(
        "--output-mask-suffix",
        default="_mask",
        help="Suffix used when --output-mask-mode=suffix",
    )
    parser.add_argument(
        "--base-name",
        default=None,
        help="Basename override for single-file input only (default: input stem)",
    )
    return parser.parse_args()


def list_input_images(input_path: Path) -> list[Path]:
    if input_path.is_file():
        if input_path.suffix.lower() not in IMAGE_EXTENSIONS:
            raise ValueError(f"Unsupported input image extension: {input_path}")
        return [input_path]

    if not input_path.is_dir():
        raise ValueError(f"Input path does not exist: {input_path}")

    files = [p for p in sorted(input_path.iterdir()) if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
    return [p for p in files if ".mask." not in p.name.lower() and not p.stem.lower().endswith("_mask")]


def build_face_dirs(np, size: int, forward, up):
    right = np.cross(forward, up)
    right /= np.linalg.norm(right)
    up = up / np.linalg.norm(up)

    lin = (np.arange(size, dtype=np.float32) + 0.5) / size
    sx = 2.0 * lin - 1.0
    sy = 1.0 - 2.0 * lin
    xx, yy = np.meshgrid(sx, sy)

    dirs = (
        forward.reshape(1, 1, 3)
        + xx[..., None] * right.reshape(1, 1, 3)
        + yy[..., None] * up.reshape(1, 1, 3)
    )
    return dirs / np.linalg.norm(dirs, axis=2, keepdims=True)


def bilinear_sample(np, img, map_x, map_y):
    h, w = img.shape[:2]
    x0 = np.floor(map_x).astype(np.int32)
    y0 = np.floor(map_y).astype(np.int32)
    x1 = (x0 + 1) % w
    y1 = np.clip(y0 + 1, 0, h - 1)

    x0 = x0 % w
    y0 = np.clip(y0, 0, h - 1)

    wx = (map_x - x0).astype(np.float32)
    wy = (map_y - y0).astype(np.float32)

    ia = img[y0, x0]
    ib = img[y0, x1]
    ic = img[y1, x0]
    id_ = img[y1, x1]

    wa = (1 - wx) * (1 - wy)
    wb = wx * (1 - wy)
    wc = (1 - wx) * wy
    wd = wx * wy

    out = ia * wa[..., None] + ib * wb[..., None] + ic * wc[..., None] + id_ * wd[..., None]
    return np.clip(out, 0, 255).astype(np.uint8)


def nearest_sample(np, img, map_x, map_y):
    h, w = img.shape[:2]
    xi = np.rint(map_x).astype(np.int32) % w
    yi = np.clip(np.rint(map_y).astype(np.int32), 0, h - 1)
    return img[yi, xi]


def rotation_matrix_from_basis(np, forward, up):
    right = np.cross(forward, up)
    right /= np.linalg.norm(right)
    up = up / np.linalg.norm(up)
    forward = forward / np.linalg.norm(forward)
    return np.stack([right, up, forward], axis=1)


def xmp_text(ns: str, rotation, rig_id: str, rig_instance_id: str, pose_index: int) -> str:
    flat_rot = " ".join(f"{v:.9f}" for v in rotation.reshape(-1))
    return f'''<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
    <rdf:Description xmlns:xcr="{ns}"
      xcr:Version="3"
      xcr:Coordinates="absolute"
      xcr:PosePrior="locked"
      xcr:CalibrationPrior="locked"
      xcr:RotationMatrix="{flat_rot}"
      xcr:Position="0 0 0"
      xcr:Rig="{rig_id}"
      xcr:RigInstance="{rig_instance_id}"
      xcr:RigPoseIndex="{pose_index}" />
  </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>
'''


def save_image(Image, face, path: Path, image_format: str, jpg_quality: int) -> None:
    if image_format == "png":
        Image.fromarray(face).save(path, format="PNG", optimize=False)
    else:
        Image.fromarray(face).save(path, format="JPEG", quality=jpg_quality, subsampling=0, optimize=False)


def find_input_mask(image_path: Path, input_mask_suffix: str) -> Path | None:
    candidates: list[Path] = []
    for ext in IMAGE_EXTENSIONS:
        candidates.append(image_path.with_name(f"{image_path.stem}{input_mask_suffix}{ext}"))
        candidates.append(image_path.with_name(f"{image_path.name}.mask{ext}"))

    for cand in candidates:
        if cand.exists() and cand.is_file():
            return cand
    return None


def build_output_mask_name(image_out_name: str, face_base: str, args: argparse.Namespace) -> str:
    if args.output_mask_mode == "dot-mask":
        return f"{image_out_name}.mask.png"
    return f"{face_base}{args.output_mask_suffix}.png"


def process_one(
    np,
    Image,
    face_specs,
    image_path: Path,
    output_dir: Path,
    args: argparse.Namespace,
    precomputed_face_dirs: dict[str, object],
    rig_id: str,
) -> dict:
    base_name = args.base_name if (args.base_name and args.input.is_file()) else image_path.stem

    image = np.array(Image.open(image_path).convert("RGB"), dtype=np.float32)
    h, w = image.shape[:2]

    mask_arr = None
    mask_source: Path | None = None
    if args.with_masks:
        mask_source = find_input_mask(image_path, args.input_mask_suffix)
        if mask_source is None:
            raise FileNotFoundError(f"Mask not found for {image_path.name}")
        mask_arr = np.array(Image.open(mask_source).convert("L"), dtype=np.uint8)

    rig_instance_id = str(uuid.uuid4())
    manifest_faces = []

    for pose_index, (face_name, spec) in enumerate(face_specs.items()):
        dirs = precomputed_face_dirs[face_name]
        x, y, z = dirs[..., 0], dirs[..., 1], dirs[..., 2]
        lon = np.arctan2(x, z)
        lat = np.arcsin(np.clip(y, -1.0, 1.0))
        map_x = (lon / (2.0 * math.pi) + 0.5) * (w - 1)
        map_y = (0.5 - lat / math.pi) * (h - 1)

        face_rgb = bilinear_sample(np, image, map_x, map_y)
        face_base = f"{base_name}_{face_name}"
        image_name = f"{face_base}.{args.image_format}"
        image_out = output_dir / image_name
        save_image(Image, face_rgb, image_out, args.image_format, args.jpg_quality)

        rot = rotation_matrix_from_basis(np, spec["forward"], spec["up"])
        xmp_path = image_out.with_suffix(image_out.suffix + ".xmp")
        xmp_path.write_text(xmp_text(args.xmp_namespace, rot, rig_id, rig_instance_id, pose_index), encoding="utf-8")

        mask_out_name = None
        if mask_arr is not None:
            mask_face = nearest_sample(np, mask_arr, map_x, map_y)
            mask_out_name = build_output_mask_name(image_name, face_base, args)
            Image.fromarray(mask_face).save(output_dir / mask_out_name, format="PNG", optimize=False)

        manifest_faces.append(
            {
                "face": face_name,
                "image": image_name,
                "xmp": xmp_path.name,
                "mask": mask_out_name,
                "pose_index": pose_index,
                "rotation_c2w": rot.reshape(-1).tolist(),
            }
        )

    return {
        "input_image": str(image_path),
        "input_mask": str(mask_source) if mask_source else None,
        "base_name": base_name,
        "rig_instance_id": rig_instance_id,
        "faces": manifest_faces,
    }


def main() -> None:
    args = parse_args()
    np, Image = require_runtime_dependencies()
    face_specs = build_face_specs(np)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    images = list_input_images(args.input)
    if not images:
        raise RuntimeError("No input images found.")

    rig_id = str(uuid.uuid4())
    precomputed_face_dirs = {
        face_name: build_face_dirs(np, args.face_size, spec["forward"], spec["up"])
        for face_name, spec in face_specs.items()
    }

    manifest_items = [
        process_one(np, Image, face_specs, img, args.output_dir, args, precomputed_face_dirs, rig_id)
        for img in images
    ]

    manifest = {
        "source": str(args.input),
        "face_size": args.face_size,
        "rig_id": rig_id,
        "with_masks": args.with_masks,
        "output_mask_mode": args.output_mask_mode if args.with_masks else None,
        "items": manifest_items,
    }
    (args.output_dir / "cubemap_rig_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
