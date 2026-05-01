from pathlib import Path
import argparse
import json
import struct

import numpy as np
import potpourri3d as pp3d


RENDER_CAMERA_POS = np.asarray((4.9, -6.55, 3.95), dtype=np.float64)
GROUND_Z = -0.92
GROUND_CLEARANCE = 0.015


PLY_SCALAR_DTYPES = {
    "char": "i1",
    "uchar": "u1",
    "int8": "i1",
    "uint8": "u1",
    "short": "i2",
    "ushort": "u2",
    "int16": "i2",
    "uint16": "u2",
    "int": "i4",
    "uint": "u4",
    "int32": "i4",
    "uint32": "u4",
    "float": "f4",
    "float32": "f4",
    "double": "f8",
    "float64": "f8",
}

PLY_STRUCT_CODES = {
    "char": "b",
    "uchar": "B",
    "int8": "b",
    "uint8": "B",
    "short": "h",
    "ushort": "H",
    "int16": "h",
    "uint16": "H",
    "int": "i",
    "uint": "I",
    "int32": "i",
    "uint32": "I",
    "float": "f",
    "float32": "f",
    "double": "d",
    "float64": "d",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Compute robust heat-method distances on a mesh and save them to an .npz file."
    )
    parser.add_argument("--mesh", required=True, type=str, help="Input PLY mesh path.")
    parser.add_argument("--output", required=True, type=str, help="Output .npz path.")
    parser.add_argument("--source-x", type=float, default=0.82)
    parser.add_argument("--source-y", type=float, default=-0.18)
    parser.add_argument("--source-z", type=float, default=-0.18)
    parser.add_argument(
        "--source-mode",
        type=str,
        default="camera_bbox_visible",
        choices=["camera_bbox_visible", "fixed_hint_visible"],
        help="How to choose the heat source vertex.",
    )
    parser.add_argument(
        "--camera-override",
        type=str,
        default="",
        help="Optional per-model camera JSON. When provided, source selection follows this view direction.",
    )
    parser.add_argument("--fit-size", type=float, default=2.4)
    parser.add_argument("--t-coef", type=float, default=1.0)
    return parser.parse_args()


def parse_ply_header(handle):
    first = handle.readline().decode("ascii").strip()
    if first != "ply":
        raise ValueError("Not a PLY file.")

    fmt = None
    vertex_count = 0
    face_count = 0
    current_element = None
    vertex_properties = []
    face_list_types = None

    while True:
        line = handle.readline().decode("ascii")
        if not line:
            raise ValueError("Unexpected EOF while reading PLY header.")
        line = line.strip()
        if line == "end_header":
            break
        if not line or line.startswith("comment"):
            continue

        parts = line.split()
        if parts[0] == "format":
            fmt = parts[1]
        elif parts[0] == "element":
            current_element = parts[1]
            if current_element == "vertex":
                vertex_count = int(parts[2])
            elif current_element == "face":
                face_count = int(parts[2])
        elif parts[0] == "property":
            if current_element == "vertex":
                if parts[1] == "list":
                    raise ValueError("List-valued vertex properties are not supported.")
                vertex_properties.append((parts[2], parts[1]))
            elif current_element == "face":
                if parts[1] != "list":
                    raise ValueError("Only list-valued face indices are supported.")
                face_list_types = (parts[2], parts[3], parts[4])

    if fmt not in {"binary_little_endian", "ascii"}:
        raise ValueError(f"Unsupported PLY format: {fmt}")
    if face_list_types is None:
        raise ValueError("PLY face list property not found.")
    return fmt, vertex_count, face_count, vertex_properties, face_list_types


def load_ply(mesh_path):
    mesh_path = Path(mesh_path)
    with mesh_path.open("rb") as handle:
        fmt, vertex_count, face_count, vertex_properties, face_list_types = parse_ply_header(handle)

        if fmt == "ascii":
            return load_ascii_ply(handle, vertex_count, face_count, vertex_properties)
        return load_binary_little_endian_ply(
            handle, vertex_count, face_count, vertex_properties, face_list_types
        )


def load_ascii_ply(handle, vertex_count, face_count, vertex_properties):
    property_names = [name for name, _dtype in vertex_properties]
    x_idx = property_names.index("x")
    y_idx = property_names.index("y")
    z_idx = property_names.index("z")

    vertices = np.empty((vertex_count, 3), dtype=np.float64)
    for i in range(vertex_count):
        parts = handle.readline().decode("ascii").strip().split()
        vertices[i] = (float(parts[x_idx]), float(parts[y_idx]), float(parts[z_idx]))

    faces = []
    for _ in range(face_count):
        parts = handle.readline().decode("ascii").strip().split()
        count = int(parts[0])
        indices = [int(v) for v in parts[1 : 1 + count]]
        faces.extend(triangulate_face(indices))
    return vertices, np.asarray(faces, dtype=np.int32)


def load_binary_little_endian_ply(handle, vertex_count, face_count, vertex_properties, face_list_types):
    dtype_fields = []
    for name, ply_type in vertex_properties:
        dtype_fields.append((name, "<" + PLY_SCALAR_DTYPES[ply_type]))
    vertex_dtype = np.dtype(dtype_fields)
    vertex_block = np.fromfile(handle, dtype=vertex_dtype, count=vertex_count)
    vertices = np.stack(
        [vertex_block["x"], vertex_block["y"], vertex_block["z"]],
        axis=1,
    ).astype(np.float64, copy=False)

    count_type, index_type, _prop_name = face_list_types
    count_fmt = "<" + PLY_STRUCT_CODES[count_type]
    index_fmt = "<" + PLY_STRUCT_CODES[index_type]
    index_dtype = np.dtype("<" + PLY_SCALAR_DTYPES[index_type])
    count_size = struct.calcsize(count_fmt)
    index_size = index_dtype.itemsize

    faces = []
    for _ in range(face_count):
        count = struct.unpack(count_fmt, handle.read(count_size))[0]
        face = np.frombuffer(handle.read(int(count) * index_size), dtype=index_dtype, count=int(count))
        faces.extend(triangulate_face(face.tolist()))
    return vertices, np.asarray(faces, dtype=np.int32)


def triangulate_face(indices):
    if len(indices) < 3:
        return []
    if len(indices) == 3:
        return [indices]
    return [[indices[0], indices[i], indices[i + 1]] for i in range(1, len(indices) - 1)]


def normalize_vertices(vertices, fit_size):
    bbox_min = vertices.min(axis=0)
    bbox_max = vertices.max(axis=0)
    center = 0.5 * (bbox_min + bbox_max)
    max_dim = float(np.max(bbox_max - bbox_min))
    scale = fit_size / max(max_dim, 1e-8)
    vertices = (vertices - center[None, :]) * scale
    z_shift = (GROUND_Z + GROUND_CLEARANCE) - float(vertices[:, 2].min())
    vertices[:, 2] += z_shift
    return vertices


def load_camera_override(camera_override_path):
    if not camera_override_path:
        return None
    path = Path(camera_override_path).resolve()
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def get_camera_position_from_override(camera_override):
    if not camera_override:
        return np.asarray(RENDER_CAMERA_POS, dtype=np.float64)
    for key in ("exact_location", "position_hint", "location"):
        if key in camera_override:
            return np.asarray(camera_override[key], dtype=np.float64)
    return np.asarray(RENDER_CAMERA_POS, dtype=np.float64)


def compute_vertex_normals(vertices, faces):
    normals = np.zeros_like(vertices, dtype=np.float64)
    tri = vertices[faces]
    face_normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    face_lengths = np.linalg.norm(face_normals, axis=1)
    valid = face_lengths > 1e-12
    face_normals[valid] /= face_lengths[valid, None]

    for corner in range(3):
        np.add.at(normals, faces[:, corner], face_normals)

    lengths = np.linalg.norm(normals, axis=1)
    valid = lengths > 1e-12
    normals[valid] /= lengths[valid, None]
    return normals


def compute_camera_side_bbox_target(vertices, camera_pos):
    bbox_min = vertices.min(axis=0)
    bbox_max = vertices.max(axis=0)
    center = 0.5 * (bbox_min + bbox_max)
    direction = np.asarray(camera_pos, dtype=np.float64) - center
    direction_norm = np.linalg.norm(direction)
    if direction_norm <= 1e-12:
        return center.copy()
    direction /= direction_norm

    ts = []
    for axis in range(3):
        if abs(direction[axis]) <= 1e-12:
            continue
        if direction[axis] > 0.0:
            t = (bbox_max[axis] - center[axis]) / direction[axis]
        else:
            t = (bbox_min[axis] - center[axis]) / direction[axis]
        if t > 0.0:
            ts.append(float(t))
    if not ts:
        return center.copy()
    return center + min(ts) * direction


def choose_source_vertex(vertices, faces, source_xyz, source_mode, camera_pos):
    if source_mode == "camera_bbox_visible":
        target_point = compute_camera_side_bbox_target(vertices, camera_pos)
    else:
        target_point = np.asarray(source_xyz, dtype=np.float64)

    distances = np.linalg.norm(vertices - target_point[None, :], axis=1)
    normals = compute_vertex_normals(vertices, faces)
    view_dirs = np.asarray(camera_pos, dtype=np.float64)[None, :] - vertices
    view_lengths = np.linalg.norm(view_dirs, axis=1)
    valid_view = view_lengths > 1e-12
    view_dirs[valid_view] /= view_lengths[valid_view, None]
    facing_score = np.einsum("ij,ij->i", normals, view_dirs)

    visible_mask = facing_score > 0.12
    if np.any(visible_mask):
        visible_indices = np.flatnonzero(visible_mask)
        local_choice = int(np.argmin(distances[visible_mask]))
        return int(visible_indices[local_choice]), target_point

    return int(np.argmin(distances)), target_point


def main():
    args = parse_args()
    mesh_path = Path(args.mesh).resolve()
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    vertices, faces = load_ply(mesh_path)
    vertices = normalize_vertices(vertices, args.fit_size)
    camera_override = load_camera_override(args.camera_override)
    camera_pos = get_camera_position_from_override(camera_override)
    source_idx, source_target_xyz = choose_source_vertex(
        vertices,
        faces,
        (args.source_x, args.source_y, args.source_z),
        args.source_mode,
        camera_pos,
    )

    solver = pp3d.MeshHeatMethodDistanceSolver(
        np.asarray(vertices, dtype=np.float64),
        np.asarray(faces, dtype=np.int32),
        t_coef=float(args.t_coef),
        use_robust=True,
    )
    distances = np.asarray(solver.compute_distance(source_idx), dtype=np.float64)

    np.savez(
        output_path,
        distances=distances,
        source_idx=np.asarray(source_idx, dtype=np.int32),
        vertex_count=np.asarray(len(vertices), dtype=np.int32),
        face_count=np.asarray(len(faces), dtype=np.int32),
        mesh_path=np.asarray(str(mesh_path)),
        fit_size=np.asarray(float(args.fit_size), dtype=np.float64),
        source_xyz=np.asarray(source_target_xyz, dtype=np.float64),
        source_hint_xyz=np.asarray((args.source_x, args.source_y, args.source_z), dtype=np.float64),
        source_mode=np.asarray(args.source_mode),
        camera_pos=np.asarray(camera_pos, dtype=np.float64),
        t_coef=np.asarray(float(args.t_coef), dtype=np.float64),
    )

    print(f"Vertices: {len(vertices)}")
    print(f"Faces: {len(faces)}")
    print(f"Source vertex: {source_idx}")
    print(f"Source target xyz: {source_target_xyz}")
    print(f"Camera position for source selection: {camera_pos}")
    print(f"Saved distances: {output_path}")


if __name__ == "__main__":
    main()
