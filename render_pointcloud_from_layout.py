from __future__ import annotations

from pathlib import Path
import argparse
import struct
import sys

import bpy
import numpy as np
from mathutils import Vector


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


def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    p = argparse.ArgumentParser(description="Render a PLY point cloud using an existing portable plastic blend layout.")
    p.add_argument("--source-blend", required=True)
    p.add_argument("--pointcloud", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--save-blend", default="")
    p.add_argument("--resolution-x", type=int, default=0)
    p.add_argument("--resolution-y", type=int, default=0)
    p.add_argument("--samples", type=int, default=96)
    p.add_argument("--fit-size", type=float, default=2.4)
    p.add_argument("--point-size", type=float, default=0.012)
    p.add_argument("--color", nargs=3, type=float, default=(0.72, 0.76, 0.82))
    return p.parse_args(argv)


def parse_ply_header(handle):
    first = handle.readline().decode("ascii").strip()
    if first != "ply":
        raise ValueError("Not a PLY file.")

    fmt = None
    vertex_count = 0
    current_element = None
    vertex_properties = []
    skip_bytes_after_vertices = 0

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
        elif parts[0] == "property" and current_element == "vertex":
            if parts[1] == "list":
                raise ValueError("List-valued vertex properties are not supported.")
            vertex_properties.append((parts[2], parts[1]))

    if fmt not in {"binary_little_endian", "ascii"}:
        raise ValueError(f"Unsupported PLY format: {fmt}")
    if vertex_count <= 0:
        raise ValueError("PLY has no vertices.")
    return fmt, vertex_count, vertex_properties, skip_bytes_after_vertices


def load_points(path: Path) -> np.ndarray:
    with path.open("rb") as handle:
        fmt, vertex_count, vertex_properties, _skip = parse_ply_header(handle)
        names = [name for name, _dtype in vertex_properties]
        for required in ("x", "y", "z"):
            if required not in names:
                raise ValueError(f"PLY vertex property missing: {required}")

        if fmt == "ascii":
            rows = []
            x_idx, y_idx, z_idx = names.index("x"), names.index("y"), names.index("z")
            for _ in range(vertex_count):
                parts = handle.readline().decode("ascii").strip().split()
                rows.append((float(parts[x_idx]), float(parts[y_idx]), float(parts[z_idx])))
            return np.asarray(rows, dtype=np.float32)

        dtype_fields = [(name, "<" + PLY_SCALAR_DTYPES[ply_type]) for name, ply_type in vertex_properties]
        data = np.fromfile(handle, dtype=np.dtype(dtype_fields), count=vertex_count)
        return np.stack([data["x"], data["y"], data["z"]], axis=1).astype(np.float32, copy=False)


def normalize_points(points: np.ndarray, fit_size: float) -> np.ndarray:
    bbox_min = points.min(axis=0)
    bbox_max = points.max(axis=0)
    center = 0.5 * (bbox_min + bbox_max)
    max_dim = float(np.max(bbox_max - bbox_min))
    out = (points - center[None, :]) * (fit_size / max(max_dim, 1e-8))
    z_shift = (GROUND_Z + GROUND_CLEARANCE) - float(out[:, 2].min())
    out[:, 2] += z_shift
    return out.astype(np.float32, copy=False)


def base_name(name: str) -> str:
    return name.split(".")[0]


def largest_subject_mesh(scene):
    meshes = [
        obj
        for obj in scene.objects
        if obj.type == "MESH"
        and not obj.name.lower().startswith("plane")
        and len(obj.data.vertices) > 0
    ]
    preferred = [obj for obj in meshes if base_name(obj.name) == "surface_contour_subject"]
    if preferred:
        return preferred[0]
    return max(meshes, key=lambda obj: len(obj.data.vertices)) if meshes else None


def make_material(color):
    mat = bpy.data.materials.new("gt_pointcloud_plastic")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    for node in list(nodes):
        if node.name != "Material Output":
            nodes.remove(node)
    output = nodes["Material Output"]
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = (float(color[0]), float(color[1]), float(color[2]), 1.0)
    bsdf.inputs["Roughness"].default_value = 0.62
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.18
    mat.node_tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    return mat


def add_geometry_nodes(point_obj, sphere_obj):
    group = bpy.data.node_groups.new("gt_pointcloud_instances", "GeometryNodeTree")
    group.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    group.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")

    nodes = group.nodes
    links = group.links
    input_node = nodes.new("NodeGroupInput")
    input_node.location = (-600, 0)
    object_info = nodes.new("GeometryNodeObjectInfo")
    object_info.location = (-380, -120)
    instance = nodes.new("GeometryNodeInstanceOnPoints")
    instance.location = (-120, 0)
    realize = nodes.new("GeometryNodeRealizeInstances")
    realize.location = (120, 0)
    output_node = nodes.new("NodeGroupOutput")
    output_node.location = (360, 0)

    object_info.inputs["Object"].default_value = sphere_obj
    if "As Instance" in object_info.inputs:
        object_info.inputs["As Instance"].default_value = True

    links.new(input_node.outputs["Geometry"], instance.inputs["Points"])
    links.new(object_info.outputs["Geometry"], instance.inputs["Instance"])
    links.new(instance.outputs["Instances"], realize.inputs["Geometry"])
    links.new(realize.outputs["Geometry"], output_node.inputs["Geometry"])

    modifier = point_obj.modifiers.new("gt_pointcloud_instances", "NODES")
    modifier.node_group = group


def configure_output(scene, resolution_x: int, resolution_y: int, samples: int):
    scene.render.engine = "CYCLES"
    scene.cycles.samples = int(samples)
    scene.cycles.device = "GPU"
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "16"
    if resolution_x > 0:
        scene.render.resolution_x = int(resolution_x)
    if resolution_y > 0:
        scene.render.resolution_y = int(resolution_y)
    scene.use_nodes = False
    for obj in scene.objects:
        if obj.type == "MESH" and obj.name.lower().startswith("plane"):
            obj.hide_render = True
            obj.hide_viewport = True
            if hasattr(obj, "is_shadow_catcher"):
                obj.is_shadow_catcher = False


def main():
    args = parse_args()
    bpy.ops.wm.open_mainfile(filepath=str(Path(args.source_blend).resolve()))
    scene = bpy.context.scene
    subject = largest_subject_mesh(scene)
    if subject is None:
        raise RuntimeError("Source blend has no subject mesh.")

    subject_transform = subject.matrix_world.copy()
    subject.hide_render = True
    subject.hide_viewport = True

    for obj in scene.objects:
        if obj.type == "CURVE" and "nonmanifold_edge_overlay" in obj.name:
            obj.hide_render = True
            obj.hide_viewport = True

    points = normalize_points(load_points(Path(args.pointcloud).resolve()), args.fit_size)
    mesh = bpy.data.meshes.new("gt_pointcloud_points_mesh")
    mesh.from_pydata([tuple(p) for p in points], [], [])
    mesh.update()
    point_obj = bpy.data.objects.new("gt_pointcloud_points", mesh)
    bpy.context.collection.objects.link(point_obj)
    point_obj.matrix_world = subject_transform

    mat = make_material(args.color)
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=float(args.point_size), location=(0.0, 0.0, 0.0))
    sphere = bpy.context.object
    sphere.name = "gt_pointcloud_instance_sphere"
    sphere.data.materials.append(mat)
    sphere.hide_viewport = True
    sphere.hide_render = True
    add_geometry_nodes(point_obj, sphere)

    configure_output(scene, args.resolution_x, args.resolution_y, args.samples)
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(output)
    bpy.ops.render.render(write_still=True)

    if args.save_blend:
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(args.save_blend).resolve()))


if __name__ == "__main__":
    main()
