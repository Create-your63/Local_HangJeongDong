#!/usr/bin/env python3
"""Batch-convert equirectangular images (+optional masks) into cubemap rig sets.

For each source image, this script creates six perspective cubemap faces, six XMP
sidecars (locked as one rigid rig at same position), and optional six mask faces
whose names follow a configurable template that can match RealityCapture/RealityScan
filename pairing rules.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple
import uuid

from PIL import Image

FACE_SPECS = {
    "front": {"forward": (0.0, 0.0, 1.0), "up": (0.0, 1.0, 0.0)},
    "right": {"forward": (1.0, 0.0, 0.0), "up": (0.0, 1.0, 0.0)},
    "back": {"forward": (0.0, 0.0, -1.0), "up": (0.0, 1.0, 0.0)},
    "left": {"forward": (-1.0, 0.0, 0.0), "up": (0.0, 1.0, 0.0)},
    "up": {"forward": (0.0, 1.0, 0.0), "up": (0.0, 0.0, -1.0)},
    "down": {"forward": (0.0, -1.0, 0.0), "up": (0.0, 0.0, 1.0)},
}

SUPPORTED_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Convert equirectangular images/masks to cubemap rig data")
    p.add_argument("input_dir", type=Path, help="Directory containing equirectangular images")
    p.add_argument("output_dir", type=Path, help="Directory for cubemap outputs")
    p.add_argument("--mask-dir", type=Path, help="Directory containing mask images paired by stem")
    p.add_argument("--mask-suffix", default="_mask", help="Mask filename suffix in mask-dir mode (default: _mask)")
    p.add_argument("--face-size", type=int, default=1536)
    p.add_argument("--image-format", choices=["png", "jpg"], default="png")
    p.add_argument("--jpg-quality", type=int, default=98)
    p.add_argument("--image-name-template", default="{stem}_{face}.{ext}", help="Output image name template")
    p.add_argument("--mask-name-template", default="{stem}_{face}_mask.png", help="Output mask name template")
    p.add_argument("--xmp-namespace", default="http://www.capturingreality.com/ns/xcr/1.1#")
    return p.parse_args()


def norm(v: Tuple[float, float, float]) -> Tuple[float, float, float]:
    n = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    return (v[0] / n, v[1] / n, v[2] / n)


def cross(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> Tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def rotation_matrix(forward: Tuple[float, float, float], up: Tuple[float, float, float]) -> List[float]:
    right = norm(cross(forward, up))
    upn = norm(up)
    fwd = norm(forward)
    # columns: right, up, forward
    return [right[0], upn[0], fwd[0], right[1], upn[1], fwd[1], right[2], upn[2], fwd[2]]


def xmp_text(ns: str, rot: List[float], rig_id: str, rig_instance: str, pose_idx: int) -> str:
    rot_s = " ".join(f"{v:.9f}" for v in rot)
    return f'''<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
    <rdf:Description xmlns:xcr="{ns}"
      xcr:Version="3"
      xcr:Coordinates="absolute"
      xcr:PosePrior="locked"
      xcr:CalibrationPrior="locked"
      xcr:RotationMatrix="{rot_s}"
      xcr:Position="0 0 0"
      xcr:Rig="{rig_id}"
      xcr:RigInstance="{rig_instance}"
      xcr:RigPoseIndex="{pose_idx}" />
  </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>
'''


@dataclass
class MapPoint:
    x0: int
    x1: int
    y0: int
    y1: int
    wx: float
    wy: float


def build_map(face_size: int, width: int, height: int, forward: Tuple[float, float, float], up: Tuple[float, float, float]) -> List[List[MapPoint]]:
    right = norm(cross(forward, up))
    upn = norm(up)
    m: List[List[MapPoint]] = []
    for j in range(face_size):
        sy = 1.0 - 2.0 * ((j + 0.5) / face_size)
        row: List[MapPoint] = []
        for i in range(face_size):
            sx = 2.0 * ((i + 0.5) / face_size) - 1.0
            dx = forward[0] + sx * right[0] + sy * upn[0]
            dy = forward[1] + sx * right[1] + sy * upn[1]
            dz = forward[2] + sx * right[2] + sy * upn[2]
            dn = math.sqrt(dx * dx + dy * dy + dz * dz)
            dx, dy, dz = dx / dn, dy / dn, dz / dn

            lon = math.atan2(dx, dz)
            lat = math.asin(max(-1.0, min(1.0, dy)))
            fx = (lon / (2.0 * math.pi) + 0.5) * (width - 1)
            fy = (0.5 - lat / math.pi) * (height - 1)

            x0 = int(math.floor(fx)) % width
            y0 = max(0, min(height - 1, int(math.floor(fy))))
            x1 = (x0 + 1) % width
            y1 = max(0, min(height - 1, y0 + 1))
            row.append(MapPoint(x0, x1, y0, y1, fx - math.floor(fx), fy - math.floor(fy)))
        m.append(row)
    return m


def sample_image(src: Image.Image, mapping: List[List[MapPoint]], nearest: bool = False) -> Image.Image:
    mode = src.mode
    bands = len(src.getbands())
    out = Image.new(mode, (len(mapping[0]), len(mapping)))
    spx = src.load()
    opx = out.load()

    for y, row in enumerate(mapping):
        for x, p in enumerate(row):
            if nearest:
                nx = p.x0 if p.wx < 0.5 else p.x1
                ny = p.y0 if p.wy < 0.5 else p.y1
                opx[x, y] = spx[nx, ny]
                continue

            a = spx[p.x0, p.y0]
            b = spx[p.x1, p.y0]
            c = spx[p.x0, p.y1]
            d = spx[p.x1, p.y1]
            if bands == 1:
                va = a * (1 - p.wx) * (1 - p.wy) + b * p.wx * (1 - p.wy) + c * (1 - p.wx) * p.wy + d * p.wx * p.wy
                opx[x, y] = int(round(max(0, min(255, va))))
            else:
                vals = []
                for ch in range(bands):
                    va = a[ch] * (1 - p.wx) * (1 - p.wy) + b[ch] * p.wx * (1 - p.wy) + c[ch] * (1 - p.wx) * p.wy + d[ch] * p.wx * p.wy
                    vals.append(int(round(max(0, min(255, va)))))
                opx[x, y] = tuple(vals)
    return out


def find_images(input_dir: Path) -> List[Path]:
    items = [p for p in sorted(input_dir.iterdir()) if p.is_file() and p.suffix.lower() in SUPPORTED_EXT]
    return [p for p in items if not p.name.endswith(".xmp")]


def find_mask(image_path: Path, args: argparse.Namespace) -> Optional[Path]:
    if not args.mask_dir:
        return None
    candidates = [
        args.mask_dir / f"{image_path.stem}{args.mask_suffix}{image_path.suffix}",
        args.mask_dir / f"{image_path.stem}{args.mask_suffix}.png",
        args.mask_dir / f"{image_path.stem}.png",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def render_name(tmpl: str, stem: str, face: str, ext: str) -> str:
    return tmpl.format(stem=stem, face=face, ext=ext)


def run(args: argparse.Namespace) -> None:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    images = find_images(args.input_dir)
    all_manifest = []

    for image_path in images:
        src = Image.open(image_path).convert("RGB")
        w, h = src.size
        mask_path = find_mask(image_path, args)
        mask_img = Image.open(mask_path).convert("L") if mask_path else None

        rig_id = str(uuid.uuid4())
        rig_instance = str(uuid.uuid4())
        frame_manifest = {
            "input_image": str(image_path),
            "input_mask": str(mask_path) if mask_path else None,
            "rig_id": rig_id,
            "rig_instance_id": rig_instance,
            "faces": [],
        }

        for pose_idx, (face, spec) in enumerate(FACE_SPECS.items()):
            mapping = build_map(args.face_size, w, h, spec["forward"], spec["up"])
            out_img = sample_image(src, mapping, nearest=False)

            out_name = render_name(args.image_name_template, image_path.stem, face, args.image_format)
            out_path = args.output_dir / out_name
            if args.image_format == "png":
                out_img.save(out_path, format="PNG", optimize=False)
            else:
                out_img.save(out_path, format="JPEG", quality=args.jpg_quality, subsampling=0, optimize=False)

            if mask_img is not None:
                out_mask = sample_image(mask_img, mapping, nearest=True)
                mask_name = render_name(args.mask_name_template, image_path.stem, face, "png")
                (args.output_dir / mask_name).parent.mkdir(parents=True, exist_ok=True)
                out_mask.save(args.output_dir / mask_name, format="PNG", optimize=False)
            else:
                mask_name = None

            rot = rotation_matrix(spec["forward"], spec["up"])
            xmp_path = out_path.with_suffix(out_path.suffix + ".xmp")
            xmp_path.write_text(xmp_text(args.xmp_namespace, rot, rig_id, rig_instance, pose_idx), encoding="utf-8")

            frame_manifest["faces"].append(
                {
                    "face": face,
                    "image": out_name,
                    "xmp": xmp_path.name,
                    "mask": mask_name,
                    "pose_index": pose_idx,
                    "rotation_c2w": rot,
                }
            )

        all_manifest.append(frame_manifest)

    (args.output_dir / "cubemap_rig_manifest.json").write_text(json.dumps(all_manifest, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    run(parse_args())
