from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from plyfile import PlyData, PlyElement


def parse_args():
    parser = argparse.ArgumentParser(
        description="Cut a PLY point cloud by deleting points inside one or more cutter meshes."
    )
    parser.add_argument("--pointcloud", required=True, help="Input point cloud PLY.")
    parser.add_argument("--output", required=True, help="Output point cloud PLY.")
    parser.add_argument("--cutter", nargs="+", required=True, help="Cutter mesh PLY paths.")
    parser.add_argument(
        "--operation",
        default="DIFFERENCE",
        choices=["DIFFERENCE", "INTERSECT"],
        help="DIFFERENCE removes points inside cutters; INTERSECT keeps points inside all cutters.",
    )
    parser.add_argument("--epsilon", type=float, default=1e-6)
    return parser.parse_args()


def read_xyz(vertex_array) -> np.ndarray:
    names = vertex_array.dtype.names or ()
    missing = [name for name in ("x", "y", "z") if name not in names]
    if missing:
        raise ValueError(f"Point cloud is missing coordinate fields: {', '.join(missing)}")
    return np.column_stack([vertex_array["x"], vertex_array["y"], vertex_array["z"]]).astype(np.float64)


def face_indices(face_value) -> list[int]:
    if isinstance(face_value, np.ndarray):
        return [int(v) for v in face_value.tolist()]
    return [int(v) for v in face_value]


def cutter_halfspace_planes(cutter_path: Path, epsilon: float) -> list[tuple[np.ndarray, np.ndarray]]:
    cutter = PlyData.read(str(cutter_path))
    verts = cutter["vertex"].data
    xyz = read_xyz(verts)
    if len(xyz) == 0:
        raise ValueError(f"Cutter has no vertices: {cutter_path}")
    if "face" not in cutter:
        raise ValueError(f"Cutter has no faces: {cutter_path}")

    center = xyz.mean(axis=0)
    planes: list[tuple[np.ndarray, np.ndarray]] = []
    seen = set()
    for face in cutter["face"].data:
        indices = face_indices(face["vertex_indices"])
        if len(indices) < 3:
            continue
        p0, p1, p2 = xyz[indices[0]], xyz[indices[1]], xyz[indices[2]]
        normal = np.cross(p1 - p0, p2 - p0)
        length = np.linalg.norm(normal)
        if length <= epsilon:
            continue
        normal = normal / length

        # Use outward-facing normals so inside means dot(point - plane_point, normal) <= 0.
        if np.dot(center - p0, normal) > 0.0:
            normal = -normal

        key = (
            round(float(normal[0]), 6),
            round(float(normal[1]), 6),
            round(float(normal[2]), 6),
            round(float(np.dot(normal, p0)), 6),
        )
        if key in seen:
            continue
        seen.add(key)
        planes.append((p0.copy(), normal.copy()))

    if not planes:
        raise ValueError(f"No valid cutter planes found: {cutter_path}")
    return planes


def points_inside_planes(points: np.ndarray, planes: list[tuple[np.ndarray, np.ndarray]], epsilon: float) -> np.ndarray:
    inside = np.ones(len(points), dtype=bool)
    for plane_point, plane_normal in planes:
        inside &= ((points - plane_point) @ plane_normal) <= epsilon
    return inside


def main():
    args = parse_args()
    pointcloud_path = Path(args.pointcloud).resolve()
    output_path = Path(args.output).resolve()
    cutter_paths = [Path(path).resolve() for path in args.cutter]

    ply = PlyData.read(str(pointcloud_path))
    vertex = ply["vertex"].data
    points = read_xyz(vertex)

    if args.operation == "DIFFERENCE":
        keep = np.ones(len(points), dtype=bool)
        for cutter_path in cutter_paths:
            planes = cutter_halfspace_planes(cutter_path, args.epsilon)
            keep &= ~points_inside_planes(points, planes, args.epsilon)
    else:
        keep = np.ones(len(points), dtype=bool)
        for cutter_path in cutter_paths:
            planes = cutter_halfspace_planes(cutter_path, args.epsilon)
            keep &= points_inside_planes(points, planes, args.epsilon)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    elements = []
    for element in ply.elements:
        if element.name == "vertex":
            elements.append(PlyElement.describe(vertex[keep], "vertex"))
        else:
            elements.append(element)
    PlyData(elements, text=ply.text, byte_order=ply.byte_order).write(str(output_path))

    removed = int(len(points) - keep.sum())
    print(f"[done] pointcloud={pointcloud_path}")
    print(f"[done] output={output_path}")
    print(f"[done] kept={int(keep.sum())} removed={removed} total={len(points)}")


if __name__ == "__main__":
    main()
