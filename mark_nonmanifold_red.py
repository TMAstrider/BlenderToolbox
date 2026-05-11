from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

import numpy as np
from plyfile import PlyData, PlyElement


def parse_args():
    parser = argparse.ArgumentParser(
        description="Mark non-manifold parts of a mesh in red and write a new PLY."
    )
    parser.add_argument("--mesh", required=True, help="Input triangle mesh PLY.")
    parser.add_argument(
        "--output",
        default="",
        help="Output PLY path. Defaults to <mesh>_red_nonmanifold_mark.ply",
    )
    parser.add_argument(
        "--base-color",
        nargs=3,
        type=int,
        default=(210, 210, 210),
        metavar=("R", "G", "B"),
        help="RGB for regular vertices. Default: 210 210 210",
    )
    parser.add_argument(
        "--mark-color",
        nargs=3,
        type=int,
        default=(255, 72, 72),
        metavar=("R", "G", "B"),
        help="RGB for non-manifold edge markers. Default: 255 72 72",
    )
    parser.add_argument(
        "--mode",
        default="edge_overlay",
        choices=["edge_overlay", "vertex_mark"],
        help="edge_overlay: keep faces neutral and add red edge tubes; "
             "vertex_mark: color vertices on non-manifold edges red.",
    )
    parser.add_argument(
        "--edge-radius",
        type=float,
        default=0.0,
        help="Overlay tube radius in world units. 0 = auto from mesh size.",
    )
    parser.add_argument(
        "--edge-radius-scale",
        type=float,
        default=0.001,
        help="When --edge-radius=0, use bbox diagonal * this scale. Default: 0.001",
    )
    parser.add_argument(
        "--edge-sides",
        type=int,
        default=6,
        help="Number of sides for red edge tubes. Default: 6",
    )
    return parser.parse_args()


def default_output_path(mesh_path: Path) -> Path:
    return mesh_path.with_name(f"{mesh_path.stem}_red_nonmanifold_mark{mesh_path.suffix}")


def load_ply(mesh_path: Path):
    ply = PlyData.read(str(mesh_path))
    if "vertex" not in ply or "face" not in ply:
        raise ValueError(f"PLY must contain vertex and face elements: {mesh_path}")

    vertex_data = ply["vertex"].data
    face_data = ply["face"].data
    vertex_props = [prop.name for prop in ply["vertex"].properties]
    face_props = [prop.name for prop in ply["face"].properties]

    if "x" not in vertex_props or "y" not in vertex_props or "z" not in vertex_props:
        raise ValueError(f"PLY vertex element must contain x/y/z: {mesh_path}")

    face_index_key = None
    for candidate in ("vertex_indices", "vertex_index"):
        if candidate in face_props:
            face_index_key = candidate
            break
    if face_index_key is None:
        raise ValueError(f"PLY face element has no vertex index list: {mesh_path}")

    verts = np.stack([vertex_data["x"], vertex_data["y"], vertex_data["z"]], axis=1).astype(np.float64)
    faces = np.array([list(face) for face in face_data[face_index_key]], dtype=np.int32)
    if faces.ndim != 2 or faces.shape[1] != 3:
        raise ValueError(f"Only triangle faces are supported: {mesh_path}")

    return ply, vertex_data, face_data, face_index_key, verts, faces


def find_nonmanifold_edges(faces: np.ndarray):
    edge_to_faces = defaultdict(list)
    for face_idx, tri in enumerate(faces):
        i0, i1, i2 = (int(tri[0]), int(tri[1]), int(tri[2]))
        for a, b in ((i0, i1), (i1, i2), (i2, i0)):
            edge = (a, b) if a < b else (b, a)
            edge_to_faces[edge].append(face_idx)
    return {edge for edge, owners in edge_to_faces.items() if len(owners) > 2}


def vertices_on_edges(edge_set: set[tuple[int, int]], vertex_count: int) -> np.ndarray:
    flags = np.zeros(vertex_count, dtype=bool)
    for a, b in edge_set:
        flags[a] = True
        flags[b] = True
    return flags


def with_vertex_colors(vertex_data, regular_mask: np.ndarray, base_color, mark_color):
    names = vertex_data.dtype.names or ()
    vertex_count = len(vertex_data)

    rgb_fields = {"red", "green", "blue"}
    existing_fields = list(vertex_data.dtype.descr)
    extra_fields = [("red", "u1"), ("green", "u1"), ("blue", "u1"), ("alpha", "u1"), ("nonmanifold_mark", "u1")]

    filtered_fields = [field for field in existing_fields if field[0] not in rgb_fields and field[0] != "alpha"]
    new_dtype = np.dtype(filtered_fields + extra_fields)
    out = np.empty(vertex_count, dtype=new_dtype)

    for field_name in out.dtype.names:
        if field_name in names and field_name not in rgb_fields and field_name != "alpha":
            out[field_name] = vertex_data[field_name]

    out["red"] = np.uint8(base_color[0])
    out["green"] = np.uint8(base_color[1])
    out["blue"] = np.uint8(base_color[2])
    out["alpha"] = np.uint8(255)

    marked = ~regular_mask
    out["red"][marked] = np.uint8(mark_color[0])
    out["green"][marked] = np.uint8(mark_color[1])
    out["blue"][marked] = np.uint8(mark_color[2])
    out["nonmanifold_mark"] = np.uint8(0)
    out["nonmanifold_mark"][marked] = np.uint8(1)
    return out


def build_uniform_vertex_array(verts: np.ndarray, color, mark_value: int):
    data = np.empty(
        len(verts),
        dtype=[
            ("x", "f4"),
            ("y", "f4"),
            ("z", "f4"),
            ("red", "u1"),
            ("green", "u1"),
            ("blue", "u1"),
            ("alpha", "u1"),
            ("nonmanifold_mark", "u1"),
        ],
    )
    data["x"] = verts[:, 0].astype(np.float32)
    data["y"] = verts[:, 1].astype(np.float32)
    data["z"] = verts[:, 2].astype(np.float32)
    data["red"] = np.uint8(color[0])
    data["green"] = np.uint8(color[1])
    data["blue"] = np.uint8(color[2])
    data["alpha"] = np.uint8(255)
    data["nonmanifold_mark"] = np.uint8(mark_value)
    return data


def auto_edge_radius(verts: np.ndarray, scale: float) -> float:
    mins = verts.min(axis=0)
    maxs = verts.max(axis=0)
    diagonal = float(np.linalg.norm(maxs - mins))
    if diagonal <= 0:
        return 0.01
    return max(diagonal * scale, 1e-6)


def orthonormal_frame(direction: np.ndarray):
    axis = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    if abs(float(np.dot(direction, axis))) > 0.9:
        axis = np.array([0.0, 1.0, 0.0], dtype=np.float64)
    u = np.cross(direction, axis)
    u_norm = float(np.linalg.norm(u))
    if u_norm <= 1e-12:
        axis = np.array([1.0, 0.0, 0.0], dtype=np.float64)
        u = np.cross(direction, axis)
        u_norm = float(np.linalg.norm(u))
    u /= u_norm
    v = np.cross(direction, u)
    v /= float(np.linalg.norm(v))
    return u, v


def build_edge_overlay_geometry(
    verts: np.ndarray,
    edge_set: set[tuple[int, int]],
    radius: float,
    sides: int,
):
    overlay_verts: list[np.ndarray] = []
    overlay_faces: list[tuple[int, int, int]] = []
    if not edge_set:
        return np.zeros((0, 3), dtype=np.float64), np.zeros((0, 3), dtype=np.int32)

    sides = max(int(sides), 3)
    angles = np.linspace(0.0, 2.0 * np.pi, num=sides, endpoint=False)

    for a, b in sorted(edge_set):
        p0 = verts[a]
        p1 = verts[b]
        direction = p1 - p0
        length = float(np.linalg.norm(direction))
        if length <= 1e-12:
            continue
        direction /= length
        u, v = orthonormal_frame(direction)
        base_index = len(overlay_verts)

        for center in (p0, p1):
            for angle in angles:
                offset = np.cos(angle) * u * radius + np.sin(angle) * v * radius
                overlay_verts.append(center + offset)

        for i in range(sides):
            ni = (i + 1) % sides
            a0 = base_index + i
            a1 = base_index + ni
            b0 = base_index + sides + i
            b1 = base_index + sides + ni
            overlay_faces.append((a0, b0, b1))
            overlay_faces.append((a0, b1, a1))

    if not overlay_verts:
        return np.zeros((0, 3), dtype=np.float64), np.zeros((0, 3), dtype=np.int32)

    return np.asarray(overlay_verts, dtype=np.float64), np.asarray(overlay_faces, dtype=np.int32)


def build_face_element_from_faces(faces: np.ndarray):
    face_data = np.array([(face.tolist(),) for face in faces], dtype=[("vertex_indices", "O")])
    return PlyElement.describe(face_data, "face")


def main():
    args = parse_args()
    mesh_path = Path(args.mesh).resolve()
    output_path = Path(args.output).resolve() if args.output else default_output_path(mesh_path)

    _ply, vertex_data, _face_data, _face_index_key, verts, faces = load_ply(mesh_path)
    nonmanifold_edges = find_nonmanifold_edges(faces)
    marked_vertices = vertices_on_edges(nonmanifold_edges, len(verts))
    regular_vertices = ~marked_vertices

    if args.mode == "vertex_mark":
        vertex_array = with_vertex_colors(
            vertex_data,
            regular_mask=regular_vertices,
            base_color=tuple(args.base_color),
            mark_color=tuple(args.mark_color),
        )
        output_faces = faces
        overlay_face_count = 0
        overlay_vertex_count = 0
    else:
        radius = args.edge_radius if args.edge_radius > 0 else auto_edge_radius(verts, args.edge_radius_scale)
        overlay_verts, overlay_faces = build_edge_overlay_geometry(
            verts,
            nonmanifold_edges,
            radius=radius,
            sides=args.edge_sides,
        )
        base_vertex_array = build_uniform_vertex_array(verts, tuple(args.base_color), mark_value=0)
        overlay_vertex_array = build_uniform_vertex_array(overlay_verts, tuple(args.mark_color), mark_value=1)
        vertex_array = np.concatenate([base_vertex_array, overlay_vertex_array])
        output_faces = faces
        if len(overlay_faces):
            shifted_overlay_faces = overlay_faces + len(verts)
            output_faces = np.concatenate([faces, shifted_overlay_faces], axis=0)
        overlay_face_count = int(len(overlay_faces))
        overlay_vertex_count = int(len(overlay_verts))

    vertex_el = PlyElement.describe(vertex_array, "vertex")
    face_el = build_face_element_from_faces(output_faces)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    PlyData([vertex_el, face_el], text=False).write(str(output_path))

    print(f"Input mesh:           {mesh_path}")
    print(f"Output mesh:          {output_path}")
    print(f"Vertices:             {len(verts)}")
    print(f"Faces:                {len(faces)}")
    print(f"Non-manifold edges:   {len(nonmanifold_edges)}")
    print(f"Marked vertices:      {int(marked_vertices.sum())}")
    if args.mode == "edge_overlay":
        print(f"Overlay vertices:     {overlay_vertex_count}")
        print(f"Overlay faces:        {overlay_face_count}")


if __name__ == "__main__":
    main()
