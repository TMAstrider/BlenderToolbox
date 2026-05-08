from pathlib import Path
import argparse
import colorsys
import json
import sys
import time

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector


CONDA_SITE_PACKAGES = Path(r"C:\ProgramData\anaconda3\envs\blender\Lib\site-packages")
if CONDA_SITE_PACKAGES.exists() and str(CONDA_SITE_PACKAGES) not in sys.path:
    sys.path.append(str(CONDA_SITE_PACKAGES))

GROUND_Z = -0.92
GROUND_CLEARANCE = 0.015
DEFAULT_LOOK_TARGET = (0.0, 0.0, -0.05)
DEFAULT_CAMERA_LOCATION = (4.9, -6.55, 3.95)
DEFAULT_CAMERA_FIT_MARGIN = 0.82

LIGHT_RIG_LOCAL = {
    "key": {
        "location": (-5.57764, 5.44754, 1.07495),
        "energy": 1600.0,
        "size": 6.0,
    },
    "fill": {
        "location": (2.05262, 1.79599, 2.14947),
        "energy": 16.0,
        "size": 8.6,
    },
    "top_back": {
        "location": (1.45246, 6.61704, -2.96957),
        "energy": 8.0,
        "size": 6.2,
    },
    "front_left": {
        "location": (-5.93662, 4.13149, -1.85315),
        "energy": 100.0,
        "size": 4.4,
    },
}

ITEMS = ("contour", "plastic", "nonmanifold_edges", "nonmanifold_regions")

def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []

    parser = argparse.ArgumentParser(
        description="Render geodesic surface contours directly in the material."
    )
    parser.add_argument("--mesh", type=str, default="", help="Path to obj/ply/stl mesh.")
    parser.add_argument(
        "--distance-file",
        type=str,
        default="",
        help="Optional .npy/.npz file containing a precomputed per-vertex distance field for the imported mesh.",
    )
    parser.add_argument(
        "--primitive",
        type=str,
        default="monkey",
        choices=["monkey", "plane", "cube"],
        help="Use a built-in primitive when --mesh is not provided.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="Output PNG path. Default: outputs/surface_contours.png",
    )
    parser.add_argument(
        "--blend",
        type=str,
        default="",
        help="Optional output .blend path for the contour scene. Default follows contour PNG name.",
    )
    parser.add_argument(
        "--plain-blend",
        type=str,
        default="",
        help="Optional output .blend path for the plain plastic scene. Default follows plain PNG name.",
    )
    parser.add_argument(
        "--plain-output",
        type=str,
        default="",
        help="Optional output PNG path for the plain plastic render.",
    )
    parser.add_argument(
        "--nonmanifold-output",
        type=str,
        default="",
        help="Optional output PNG path for the non-manifold edge highlight render.",
    )
    parser.add_argument(
        "--nonmanifold-blend",
        type=str,
        default="",
        help="Optional output .blend path for the non-manifold edge highlight scene.",
    )
    parser.add_argument(
        "--regions-output",
        type=str,
        default="",
        help="Optional output PNG path for the non-manifold region partition render.",
    )
    parser.add_argument(
        "--regions-blend",
        type=str,
        default="",
        help="Optional output .blend path for the non-manifold region partition scene.",
    )
    parser.add_argument("--samples", type=int, default=96, help="Cycles sample count.")
    parser.add_argument("--resolution-x", type=int, default=1600)
    parser.add_argument("--resolution-y", type=int, default=1100)
    parser.add_argument(
        "--line-density",
        type=float,
        default=8.5,
        help="Higher value means more contour lines.",
    )
    parser.add_argument(
        "--line-width",
        type=float,
        default=0.028,
        help="Smaller value means thinner contour lines.",
    )
    parser.add_argument(
        "--fit-size",
        type=float,
        default=2.4,
        help="Normalize imported mesh max dimension to this size.",
    )
    parser.add_argument(
        "--unlit",
        action="store_true",
        help="Use view-independent emission materials for diagnostics.",
    )
    parser.add_argument(
        "--distance-percentile",
        type=float,
        default=100.0,
        help="Upper percentile used to normalize distances before coloring. Use 100 for the true full range.",
    )
    parser.add_argument(
        "--camera-override",
        type=str,
        default="",
        help="Optional JSON file containing a manually tuned camera transform.",
    )
    parser.add_argument(
        "--save-only",
        action="store_true",
        help="Save the generated .blend scenes without rendering PNG outputs.",
    )
    parser.add_argument(
        "--items",
        nargs="+",
        choices=ITEMS,
        default=list(ITEMS),
        help="Which scene variants to generate.",
    )
    return parser.parse_args(argv)


def ensure_output_paths(args):
    script_dir = Path(__file__).resolve().parent
    if args.output:
        output_path = Path(args.output).resolve()
    else:
        output_path = script_dir / "outputs" / "surface_contours.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if args.blend:
        blend_path = Path(args.blend).resolve()
    else:
        blend_path = output_path.with_suffix(".blend")
    blend_path.parent.mkdir(parents=True, exist_ok=True)

    if args.plain_output:
        plain_output_path = Path(args.plain_output).resolve()
    else:
        plain_output_path = output_path.with_name(output_path.stem + "_plastic" + output_path.suffix)
    plain_output_path.parent.mkdir(parents=True, exist_ok=True)

    if args.plain_blend:
        plain_blend_path = Path(args.plain_blend).resolve()
    else:
        plain_blend_path = plain_output_path.with_suffix(".blend")
    plain_blend_path.parent.mkdir(parents=True, exist_ok=True)

    if args.nonmanifold_output:
        nonmanifold_output_path = Path(args.nonmanifold_output).resolve()
    else:
        nonmanifold_output_path = output_path.with_name(output_path.stem + "_nonmanifold_edges" + output_path.suffix)
    nonmanifold_output_path.parent.mkdir(parents=True, exist_ok=True)

    if args.nonmanifold_blend:
        nonmanifold_blend_path = Path(args.nonmanifold_blend).resolve()
    else:
        nonmanifold_blend_path = nonmanifold_output_path.with_suffix(".blend")
    nonmanifold_blend_path.parent.mkdir(parents=True, exist_ok=True)

    if args.regions_output:
        regions_output_path = Path(args.regions_output).resolve()
    else:
        regions_name = nonmanifold_output_path.name.replace("_nonmanifold_edges", "_nonmanifold_regions")
        if regions_name == nonmanifold_output_path.name:
            regions_name = nonmanifold_output_path.stem + "_regions" + nonmanifold_output_path.suffix
        regions_output_path = nonmanifold_output_path.with_name(regions_name)
    regions_output_path.parent.mkdir(parents=True, exist_ok=True)

    if args.regions_blend:
        regions_blend_path = Path(args.regions_blend).resolve()
    else:
        regions_blend_path = regions_output_path.with_suffix(".blend")
    regions_blend_path.parent.mkdir(parents=True, exist_ok=True)

    return (
        output_path,
        plain_output_path,
        nonmanifold_output_path,
        regions_output_path,
        blend_path,
        plain_blend_path,
        nonmanifold_blend_path,
        regions_blend_path,
    )


def load_precomputed_distances(distance_file):
    distance_path = Path(distance_file).resolve()
    if not distance_path.exists():
        raise FileNotFoundError(f"Distance file not found: {distance_path}")

    if distance_path.suffix.lower() == ".npz":
        payload = np.load(distance_path)
        if "distances" not in payload:
            raise KeyError(f"Distance file {distance_path} does not contain a 'distances' array.")
        distances = np.asarray(payload["distances"], dtype=np.float64)
    else:
        distances = np.asarray(np.load(distance_path), dtype=np.float64)
    return distances, distance_path


def look_at(obj, target):
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def enable_gpu():
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "GPU"

    prefs = bpy.context.preferences.addons["cycles"].preferences
    try:
        prefs.compute_device_type = "OPTIX"
    except TypeError:
        prefs.compute_device_type = "CUDA"
    prefs.get_devices()

    for device in prefs.devices:
        device.use = device.type != "CPU"
        print(f"Render device: {device.name} | {device.type} | use={device.use}")


def setup_scene(args):
    prefs = bpy.context.preferences.view
    prefs.language = "en_US"
    prefs.use_translate_interface = False
    prefs.use_translate_new_dataname = False

    enable_gpu()

    scene = bpy.context.scene
    scene.cycles.samples = args.samples
    if hasattr(scene.cycles, "use_denoising"):
        scene.cycles.use_denoising = True
    if hasattr(bpy.context.view_layer, "cycles") and hasattr(bpy.context.view_layer.cycles, "use_denoising"):
        bpy.context.view_layer.cycles.use_denoising = True
    scene.render.resolution_x = args.resolution_x
    scene.render.resolution_y = args.resolution_y
    scene.render.film_transparent = True
    scene.view_settings.view_transform = "Filmic"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = -0.02
    scene.view_settings.gamma = 1.0
    scene.world.color = (1.0, 1.0, 1.0)
    if scene.world is not None:
        scene.world.use_nodes = True
        world_nodes = scene.world.node_tree.nodes
        bg = world_nodes.get("Background")
        if bg is not None:
            bg.inputs[0].default_value = (1.0, 1.0, 1.0, 1.0)
            bg.inputs[1].default_value = 0.10
    setup_white_background_compositor(scene)


def setup_white_background_compositor(scene):
    scene.use_nodes = True
    tree = scene.node_tree
    nodes = tree.nodes
    links = tree.links

    for node in list(nodes):
        nodes.remove(node)

    render_layers = nodes.new("CompositorNodeRLayers")
    render_layers.location = (-300, 0)

    white = nodes.new("CompositorNodeRGB")
    white.location = (-300, -180)
    # Keep the composite background visually pure white after Filmic.
    white.outputs[0].default_value = (16.0, 16.0, 16.0, 1.0)

    alpha_over = nodes.new("CompositorNodeAlphaOver")
    alpha_over.location = (0, 0)

    composite = nodes.new("CompositorNodeComposite")
    composite.location = (240, 0)

    links.new(white.outputs[0], alpha_over.inputs[1])
    links.new(render_layers.outputs["Image"], alpha_over.inputs[2])
    links.new(alpha_over.outputs["Image"], composite.inputs["Image"])


def add_ground():
    mat = bpy.data.materials.new("ground_mat")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    for node in list(nodes):
        nodes.remove(node)
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (180, 0)
    diffuse = nodes.new("ShaderNodeBsdfDiffuse")
    diffuse.location = (0, 0)
    diffuse.inputs["Color"].default_value = (0.93, 0.93, 0.93, 1.0)
    diffuse.inputs["Roughness"].default_value = 1.0
    links.new(diffuse.outputs["BSDF"], output.inputs["Surface"])

    bpy.ops.mesh.primitive_plane_add(size=90, location=(0, 0, GROUND_Z))
    floor = bpy.context.object
    floor.data.materials.append(mat)
    floor.is_shadow_catcher = True


def add_lights():
    lights = {}
    for name, spec in LIGHT_RIG_LOCAL.items():
        bpy.ops.object.light_add(type="AREA", location=(0.0, 0.0, 0.0))
        light_obj = bpy.context.object
        light_obj.name = f"render_light_{name}"
        light_obj.data.energy = float(spec["energy"])
        light_obj.data.size = float(spec["size"])
        lights[name] = light_obj
    return lights


def add_camera():
    bpy.ops.object.camera_add(location=DEFAULT_CAMERA_LOCATION)
    cam = bpy.context.object
    cam.data.lens = 58
    cam.data.clip_start = 0.01
    cam.data.clip_end = 500.0
    look_at(cam, DEFAULT_LOOK_TARGET)
    bpy.context.scene.camera = cam
    return cam


def default_camera_radius(look_target=DEFAULT_LOOK_TARGET):
    return (Vector(DEFAULT_CAMERA_LOCATION) - Vector(look_target)).length


def load_camera_override(camera_override_path):
    if not camera_override_path:
        return None
    path = Path(camera_override_path).resolve()
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    data["_path"] = str(path)
    return data


def apply_camera_override(camera_obj, override):
    if not override:
        return False

    if "position_hint" in override or "view_direction" in override:
        return False

    if "location" in override:
        camera_obj.location = Vector(tuple(float(x) for x in override["location"]))

    if "rotation_euler" in override:
        camera_obj.rotation_mode = "XYZ"
        camera_obj.rotation_euler = tuple(float(x) for x in override["rotation_euler"])
    elif "look_target" in override:
        look_at(camera_obj, tuple(float(x) for x in override["look_target"]))

    if "lens" in override:
        camera_obj.data.lens = float(override["lens"])
    if "clip_start" in override:
        camera_obj.data.clip_start = float(override["clip_start"])
    if "clip_end" in override:
        camera_obj.data.clip_end = float(override["clip_end"])
    return True


def orient_camera_from_hint(camera_obj, position_hint=None, view_direction=None, look_target=DEFAULT_LOOK_TARGET):
    target = Vector(tuple(float(x) for x in look_target))
    radius = default_camera_radius(look_target)

    if position_hint is not None:
        hint_vec = Vector(tuple(float(x) for x in position_hint)) - target
    elif view_direction is not None:
        hint_vec = Vector(tuple(float(x) for x in view_direction))
    else:
        hint_vec = Vector(DEFAULT_CAMERA_LOCATION) - target

    if hint_vec.length <= 1e-8:
        hint_vec = Vector(DEFAULT_CAMERA_LOCATION) - target
    hint_vec.normalize()
    camera_obj.location = target + hint_vec * radius
    look_at(camera_obj, tuple(target))


def place_lights_relative_to_camera(lights, camera_obj, look_target=DEFAULT_LOOK_TARGET):
    target_vec = Vector(tuple(float(x) for x in look_target))
    view_dir = (target_vec - camera_obj.location).normalized()
    world_up = Vector((0.0, 0.0, 1.0))
    right = view_dir.cross(world_up)
    if right.length <= 1e-8:
        world_up = Vector((0.0, 1.0, 0.0))
        right = view_dir.cross(world_up)
    right.normalize()
    up = right.cross(view_dir).normalized()

    for name, light_obj in lights.items():
        spec = LIGHT_RIG_LOCAL[name]
        lx, ly, lz = (float(v) for v in spec["location"])
        light_obj.location = camera_obj.location + right * lx + up * ly + view_dir * (-lz)
        look_at(light_obj, tuple(target_vec))
        bpy.context.view_layer.update()
        # Store the rig in camera-local space so manual camera orbiting keeps
        # lighting visually stable instead of leaving lights behind in world space.
        relative_matrix = camera_obj.matrix_world.inverted() @ light_obj.matrix_world
        light_obj.parent = camera_obj
        light_obj.matrix_parent_inverse = Matrix.Identity(4)
        loc, rot, scale = relative_matrix.decompose()
        light_obj.location = loc
        light_obj.rotation_mode = "XYZ"
        light_obj.rotation_euler = rot.to_euler("XYZ")
        light_obj.scale = scale


def create_monkey_mesh():
    bpy.ops.mesh.primitive_monkey_add(size=1.2, location=(0, 0, 0))
    obj = bpy.context.object
    obj.name = "surface_contour_subject"
    return obj


def create_plane_mesh():
    bpy.ops.mesh.primitive_plane_add(size=2.8, location=(0, 0, 0))
    obj = bpy.context.object
    obj.name = "surface_contour_subject"
    bpy.context.view_layer.objects.active = obj
    subdiv = obj.modifiers.new(name="Subsurf", type="SUBSURF")
    subdiv.subdivision_type = "SIMPLE"
    subdiv.levels = 5
    subdiv.render_levels = 5
    bpy.ops.object.modifier_apply(modifier=subdiv.name)
    return obj


def create_cube_mesh():
    bpy.ops.mesh.primitive_cube_add(size=2.2, location=(0, 0, 0))
    obj = bpy.context.object
    obj.name = "surface_contour_subject"
    bpy.context.view_layer.objects.active = obj
    subdiv = obj.modifiers.new(name="Subsurf", type="SUBSURF")
    subdiv.subdivision_type = "SIMPLE"
    subdiv.levels = 4
    subdiv.render_levels = 4
    bpy.ops.object.modifier_apply(modifier=subdiv.name)
    return obj


def import_mesh(mesh_path):
    mesh_path = str(Path(mesh_path).resolve())
    ext = Path(mesh_path).suffix.lower()

    bpy.ops.object.select_all(action="DESELECT")
    if ext == ".obj":
        try:
            bpy.ops.wm.obj_import(filepath=mesh_path)
        except Exception:
            bpy.ops.import_scene.obj(filepath=mesh_path)
    elif ext == ".ply":
        try:
            bpy.ops.wm.ply_import(filepath=mesh_path)
        except Exception:
            bpy.ops.import_mesh.ply(filepath=mesh_path)
    elif ext == ".stl":
        try:
            bpy.ops.wm.stl_import(filepath=mesh_path)
        except Exception:
            bpy.ops.import_mesh.stl(filepath=mesh_path)
    else:
        raise ValueError("Only obj / ply / stl are supported.")

    mesh_objects = [obj for obj in bpy.context.selected_objects if obj.type == "MESH"]
    if not mesh_objects:
        raise RuntimeError("No mesh object was imported.")

    obj = max(mesh_objects, key=lambda item: len(item.data.vertices))
    obj.name = "surface_contour_subject"
    return obj


def normalize_mesh_geometry(mesh_obj, fit_size):
    mesh = mesh_obj.data
    coords = np.array([tuple(v.co) for v in mesh.vertices], dtype=float)
    bbox_min = coords.min(axis=0)
    bbox_max = coords.max(axis=0)
    center = 0.5 * (bbox_min + bbox_max)
    max_dim = float(np.max(bbox_max - bbox_min))
    scale = fit_size / max(max_dim, 1e-8)

    for vert in mesh.vertices:
        vert.co = (vert.co - Vector(center.tolist())) * scale

    mesh.update()
    shifted_coords = np.array([tuple(v.co) for v in mesh.vertices], dtype=float)
    shifted_bbox_min = shifted_coords.min(axis=0)
    z_shift = (GROUND_Z + GROUND_CLEARANCE) - float(shifted_bbox_min[2])
    if abs(z_shift) > 1e-10:
        for vert in mesh.vertices:
            vert.co.z += z_shift
    mesh.update()


def fit_camera_to_mesh(camera_obj, mesh_obj, look_target=DEFAULT_LOOK_TARGET, margin=DEFAULT_CAMERA_FIT_MARGIN):
    scene = bpy.context.scene
    camera_data = camera_obj.data
    look_at(camera_obj, look_target)

    corners = [mesh_obj.matrix_world @ Vector(corner) for corner in mesh_obj.bound_box]
    cam_inv = camera_obj.matrix_world.inverted()
    cam_space = [cam_inv @ corner for corner in corners]

    if not cam_space:
        return

    aspect = scene.render.resolution_x / max(scene.render.resolution_y, 1)
    angle_y = camera_data.angle_y
    angle_x = camera_data.angle_x if hasattr(camera_data, "angle_x") else 2.0 * np.arctan(np.tan(angle_y * 0.5) * aspect)
    tan_x = np.tan(angle_x * 0.5)
    tan_y = np.tan(angle_y * 0.5)

    required_delta = 0.0
    for point in cam_space:
        depth = -float(point.z)
        if depth <= 1e-8:
            required_delta = max(required_delta, 1.0 - depth)
            continue
        req_x = abs(float(point.x)) / max(tan_x * margin, 1e-8)
        req_y = abs(float(point.y)) / max(tan_y * margin, 1e-8)
        required_depth = max(req_x, req_y)
        required_delta = max(required_delta, required_depth - depth)

    if required_delta <= 0.0:
        return

    view_dir = (Vector(look_target) - camera_obj.location).normalized()
    camera_obj.location = camera_obj.location - view_dir * required_delta
    look_at(camera_obj, look_target)


def prepare_mesh(mesh_obj, fit_size, apply_subsurf):
    bpy.context.view_layer.objects.active = mesh_obj
    mesh_obj.select_set(True)
    bpy.ops.object.shade_flat()

    # Imported meshes may share datablocks; make this object single-user so
    # modifier application and later edits do not fail.
    mesh_obj.data = mesh_obj.data.copy()

    normalize_mesh_geometry(mesh_obj, fit_size)

    if apply_subsurf:
        subsurf = mesh_obj.modifiers.new(name="Subsurf", type="SUBSURF")
        subsurf.levels = 2
        subsurf.render_levels = 2
        bpy.ops.object.modifier_apply(modifier=subsurf.name)

    bm = bmesh.new()
    bm.from_mesh(mesh_obj.data)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.to_mesh(mesh_obj.data)
    bm.free()
    mesh_obj.data.update()
    stabilize_shading_normals(mesh_obj)


def stabilize_shading_normals(mesh_obj):
    bpy.context.view_layer.objects.active = mesh_obj
    mesh_obj.select_set(True)

    if hasattr(mesh_obj.data, "has_custom_normals") and mesh_obj.data.has_custom_normals:
        try:
            bpy.ops.mesh.customdata_custom_splitnormals_clear()
        except Exception:
            pass

    bpy.ops.object.shade_flat()
    if hasattr(mesh_obj.data, "use_auto_smooth"):
        mesh_obj.data.use_auto_smooth = False

    try:
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.normals_make_consistent(inside=False)
        bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass

    mesh_obj.data.update()


def store_distance_attributes(mesh_obj, distances, color_attr_name, line_attr_name, upper_percentile):
    finite = distances[np.isfinite(distances)]
    dmin = float(finite.min())
    dmax = float(np.percentile(finite, upper_percentile))
    scaled = (distances - dmin) / max(dmax - dmin, 1e-8)
    color_normalized = np.clip(scaled, 0.0, 1.0)

    mesh = mesh_obj.data
    for attr_name in [color_attr_name, line_attr_name]:
        if attr_name in mesh.attributes:
            mesh.attributes.remove(mesh.attributes[attr_name])

    color_attr = mesh.attributes.new(name=color_attr_name, type="FLOAT", domain="POINT")
    line_attr = mesh.attributes.new(name=line_attr_name, type="FLOAT", domain="POINT")
    for i, (color_value, line_value) in enumerate(zip(color_normalized, scaled)):
        color_attr.data[i].value = float(color_value)
        line_attr.data[i].value = float(line_value)


def configure_plastic_bsdf(bsdf, base_color):
    bsdf.inputs["Base Color"].default_value = base_color
    bsdf.inputs["Roughness"].default_value = 0.72
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.12
    if "IOR" in bsdf.inputs:
        bsdf.inputs["IOR"].default_value = 1.45


def add_two_sided_normal_setup(nodes, links, location=(-1200, -520)):
    geometry = nodes.new("ShaderNodeNewGeometry")
    geometry.location = location

    invert = nodes.new("ShaderNodeVectorMath")
    invert.operation = "SCALE"
    invert.inputs[3].default_value = -1.0
    invert.location = (location[0] + 220, location[1] - 20)

    mix = nodes.new("ShaderNodeMix")
    mix.data_type = "VECTOR"
    mix.location = (location[0] + 460, location[1] - 10)

    links.new(geometry.outputs["Normal"], invert.inputs[0])
    links.new(geometry.outputs["Backfacing"], mix.inputs["Factor"])
    links.new(geometry.outputs["Normal"], mix.inputs["A"])
    links.new(invert.outputs["Vector"], mix.inputs["B"])
    return mix.outputs["Result"]


def add_orientation_invariant_shading(nodes, links, location=(-520, -260)):
    geometry = nodes.new("ShaderNodeNewGeometry")
    geometry.location = location

    light_dir = nodes.new("ShaderNodeCombineXYZ")
    light_dir.location = (location[0] + 180, location[1] - 40)
    light_dir.inputs["X"].default_value = 0.42
    light_dir.inputs["Y"].default_value = -0.48
    light_dir.inputs["Z"].default_value = 0.77

    dot = nodes.new("ShaderNodeVectorMath")
    dot.operation = "DOT_PRODUCT"
    dot.location = (location[0] + 380, location[1] - 10)

    absolute = nodes.new("ShaderNodeMath")
    absolute.operation = "ABSOLUTE"
    absolute.location = (location[0] + 600, location[1] - 10)

    scale = nodes.new("ShaderNodeMath")
    scale.operation = "MULTIPLY"
    scale.inputs[1].default_value = 0.34
    scale.location = (location[0] + 800, location[1] - 10)

    bias = nodes.new("ShaderNodeMath")
    bias.operation = "ADD"
    bias.inputs[1].default_value = 0.66
    bias.location = (location[0] + 980, location[1] - 10)

    links.new(geometry.outputs["True Normal"], dot.inputs[0])
    links.new(light_dir.outputs["Vector"], dot.inputs[1])
    links.new(dot.outputs["Value"], absolute.inputs[0])
    links.new(absolute.outputs["Value"], scale.inputs[0])
    links.new(scale.outputs["Value"], bias.inputs[0])
    return bias.outputs["Value"]


def build_surface_contour_material(mesh_obj, color_attr_name, line_attr_name, line_density, line_width):
    mat = bpy.data.materials.new("surface_geodesic_plastic")
    mat.use_nodes = True
    mat.use_backface_culling = False
    tree = mat.node_tree
    nodes = tree.nodes
    links = tree.links

    for node in list(nodes):
        if node.name not in {"Material Output"}:
            nodes.remove(node)

    output = nodes["Material Output"]

    color_attr = nodes.new("ShaderNodeAttribute")
    color_attr.attribute_name = color_attr_name
    color_attr.location = (-1200, 0)

    line_attr = nodes.new("ShaderNodeAttribute")
    line_attr.attribute_name = line_attr_name
    line_attr.location = (-1200, -220)

    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.location = (-900, 60)
    ramp.color_ramp.interpolation = "LINEAR"
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = (0.76, 0.17, 0.14, 1.0)
    ramp.color_ramp.elements[1].position = 1.0
    ramp.color_ramp.elements[1].color = (0.09, 0.29, 0.76, 1.0)
    mid_1 = ramp.color_ramp.elements.new(0.12)
    mid_1.color = (0.85, 0.34, 0.24, 1.0)
    mid_2 = ramp.color_ramp.elements.new(0.24)
    mid_2.color = (0.88, 0.58, 0.45, 1.0)
    mid_3 = ramp.color_ramp.elements.new(0.34)
    mid_3.color = (0.56, 0.76, 0.86, 1.0)
    mid_4 = ramp.color_ramp.elements.new(0.52)
    mid_4.color = (0.34, 0.63, 0.79, 1.0)
    mid_5 = ramp.color_ramp.elements.new(0.76)
    mid_5.color = (0.18, 0.45, 0.82, 1.0)

    multiply = nodes.new("ShaderNodeMath")
    multiply.operation = "MULTIPLY"
    multiply.inputs[1].default_value = line_density
    multiply.location = (-900, -240)

    fract = nodes.new("ShaderNodeMath")
    fract.operation = "FRACT"
    fract.location = (-700, -240)

    subtract = nodes.new("ShaderNodeMath")
    subtract.operation = "SUBTRACT"
    subtract.inputs[1].default_value = 0.5
    subtract.location = (-520, -240)

    absolute = nodes.new("ShaderNodeMath")
    absolute.operation = "ABSOLUTE"
    absolute.location = (-340, -240)

    less_than = nodes.new("ShaderNodeMath")
    less_than.operation = "LESS_THAN"
    less_than.inputs[1].default_value = line_width
    less_than.location = (-140, -240)

    line_mix = nodes.new("ShaderNodeMixRGB")
    line_mix.blend_type = "MIX"
    line_mix.inputs["Color2"].default_value = (0.20, 0.24, 0.27, 1.0)
    line_mix.location = (-120, 40)

    hsv = nodes.new("ShaderNodeHueSaturation")
    hsv.inputs["Saturation"].default_value = 1.12
    hsv.inputs["Value"].default_value = 0.97
    hsv.location = (80, 60)

    shade = add_orientation_invariant_shading(nodes, links, location=(-260, -380))

    shade_mix = nodes.new("ShaderNodeMixRGB")
    shade_mix.blend_type = "MULTIPLY"
    shade_mix.inputs["Fac"].default_value = 1.0
    shade_mix.location = (320, 60)

    ao = nodes.new("ShaderNodeAmbientOcclusion")
    ao.inputs["Distance"].default_value = 1.15
    ao.location = (320, -170)

    ao_mix = nodes.new("ShaderNodeMixRGB")
    ao_mix.blend_type = "MULTIPLY"
    ao_mix.inputs["Fac"].default_value = 0.12
    ao_mix.location = (560, 60)

    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Strength"].default_value = 1.0
    emission.location = (780, 60)

    links.new(color_attr.outputs["Fac"], ramp.inputs["Fac"])
    links.new(line_attr.outputs["Fac"], multiply.inputs[0])
    links.new(multiply.outputs[0], fract.inputs[0])
    links.new(fract.outputs[0], subtract.inputs[0])
    links.new(subtract.outputs[0], absolute.inputs[0])
    links.new(absolute.outputs[0], less_than.inputs[0])
    links.new(less_than.outputs[0], line_mix.inputs["Fac"])
    links.new(ramp.outputs["Color"], line_mix.inputs["Color1"])
    links.new(line_mix.outputs["Color"], hsv.inputs["Color"])
    links.new(hsv.outputs["Color"], shade_mix.inputs["Color1"])
    links.new(shade, shade_mix.inputs["Color2"])
    links.new(shade_mix.outputs["Color"], ao_mix.inputs["Color1"])
    links.new(ao.outputs["Color"], ao_mix.inputs["Color2"])
    links.new(ao_mix.outputs["Color"], emission.inputs["Color"])
    links.new(emission.outputs["Emission"], output.inputs["Surface"])

    return mat


def build_surface_contour_unlit_material(color_attr_name, line_attr_name, line_density, line_width):
    mat = bpy.data.materials.new("surface_geodesic_unlit")
    mat.use_nodes = True
    mat.use_backface_culling = False
    tree = mat.node_tree
    nodes = tree.nodes
    links = tree.links

    for node in list(nodes):
        if node.name not in {"Material Output"}:
            nodes.remove(node)

    output = nodes["Material Output"]

    color_attr = nodes.new("ShaderNodeAttribute")
    color_attr.attribute_name = color_attr_name
    color_attr.location = (-1200, 0)

    line_attr = nodes.new("ShaderNodeAttribute")
    line_attr.attribute_name = line_attr_name
    line_attr.location = (-1200, -220)

    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.location = (-900, 60)
    ramp.color_ramp.interpolation = "LINEAR"
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = (0.76, 0.17, 0.14, 1.0)
    ramp.color_ramp.elements[1].position = 1.0
    ramp.color_ramp.elements[1].color = (0.09, 0.29, 0.76, 1.0)
    mid_1 = ramp.color_ramp.elements.new(0.12)
    mid_1.color = (0.85, 0.34, 0.24, 1.0)
    mid_2 = ramp.color_ramp.elements.new(0.24)
    mid_2.color = (0.88, 0.58, 0.45, 1.0)
    mid_3 = ramp.color_ramp.elements.new(0.34)
    mid_3.color = (0.56, 0.76, 0.86, 1.0)
    mid_4 = ramp.color_ramp.elements.new(0.52)
    mid_4.color = (0.34, 0.63, 0.79, 1.0)
    mid_5 = ramp.color_ramp.elements.new(0.76)
    mid_5.color = (0.18, 0.45, 0.82, 1.0)

    multiply = nodes.new("ShaderNodeMath")
    multiply.operation = "MULTIPLY"
    multiply.inputs[1].default_value = line_density
    multiply.location = (-900, -240)

    fract = nodes.new("ShaderNodeMath")
    fract.operation = "FRACT"
    fract.location = (-700, -240)

    subtract = nodes.new("ShaderNodeMath")
    subtract.operation = "SUBTRACT"
    subtract.inputs[1].default_value = 0.5
    subtract.location = (-520, -240)

    absolute = nodes.new("ShaderNodeMath")
    absolute.operation = "ABSOLUTE"
    absolute.location = (-340, -240)

    less_than = nodes.new("ShaderNodeMath")
    less_than.operation = "LESS_THAN"
    less_than.inputs[1].default_value = line_width
    less_than.location = (-140, -240)

    line_mix = nodes.new("ShaderNodeMixRGB")
    line_mix.blend_type = "MIX"
    line_mix.inputs["Color2"].default_value = (0.24, 0.27, 0.31, 1.0)
    line_mix.location = (-120, 40)

    hsv = nodes.new("ShaderNodeHueSaturation")
    hsv.inputs["Saturation"].default_value = 1.06
    hsv.inputs["Value"].default_value = 1.01
    hsv.location = (80, 60)

    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Strength"].default_value = 1.0
    emission.location = (320, 60)

    links.new(color_attr.outputs["Fac"], ramp.inputs["Fac"])
    links.new(line_attr.outputs["Fac"], multiply.inputs[0])
    links.new(multiply.outputs[0], fract.inputs[0])
    links.new(fract.outputs[0], subtract.inputs[0])
    links.new(subtract.outputs[0], absolute.inputs[0])
    links.new(absolute.outputs[0], less_than.inputs[0])
    links.new(less_than.outputs[0], line_mix.inputs["Fac"])
    links.new(ramp.outputs["Color"], line_mix.inputs["Color1"])
    links.new(line_mix.outputs["Color"], hsv.inputs["Color"])
    links.new(hsv.outputs["Color"], emission.inputs["Color"])
    links.new(emission.outputs["Emission"], output.inputs["Surface"])
    return mat


def build_plain_plastic_material():
    mat = bpy.data.materials.new("surface_plain_plastic")
    mat.use_nodes = True
    mat.use_backface_culling = False
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    for node in list(nodes):
        if node.name not in {"Material Output"}:
            nodes.remove(node)

    output = nodes["Material Output"]

    hsv = nodes.new("ShaderNodeHueSaturation")
    hsv.location = (-520, 80)
    hsv.inputs["Color"].default_value = (0.3082, 0.6090, 0.7405, 1.0)
    hsv.inputs["Hue"].default_value = 0.5
    hsv.inputs["Saturation"].default_value = 1.0
    hsv.inputs["Value"].default_value = 1.0

    bc = nodes.new("ShaderNodeBrightContrast")
    bc.location = (-280, 80)
    bc.inputs["Bright"].default_value = 0.0
    bc.inputs["Contrast"].default_value = 0.8

    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (-20, 30)
    bsdf.inputs["Metallic"].default_value = 0.0
    bsdf.inputs["Roughness"].default_value = 0.56
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.28
    elif "Specular" in bsdf.inputs:
        bsdf.inputs["Specular"].default_value = 0.24
    if "Alpha" in bsdf.inputs:
        bsdf.inputs["Alpha"].default_value = 1.0
    if "Transmission Weight" in bsdf.inputs:
        bsdf.inputs["Transmission Weight"].default_value = 0.0
    elif "Transmission" in bsdf.inputs:
        bsdf.inputs["Transmission"].default_value = 0.0
    if "Coat Weight" in bsdf.inputs:
        bsdf.inputs["Coat Weight"].default_value = 0.02
    elif "Clearcoat" in bsdf.inputs:
        bsdf.inputs["Clearcoat"].default_value = 0.02
    if "Coat Roughness" in bsdf.inputs:
        bsdf.inputs["Coat Roughness"].default_value = 0.60
    elif "Clearcoat Roughness" in bsdf.inputs:
        bsdf.inputs["Clearcoat Roughness"].default_value = 0.60
    if "Emission Strength" in bsdf.inputs:
        bsdf.inputs["Emission Strength"].default_value = 0.0

    links.new(hsv.outputs["Color"], bc.inputs["Color"])
    links.new(bc.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    return mat


def build_plain_unlit_material():
    mat = bpy.data.materials.new("surface_plain_unlit")
    mat.use_nodes = True
    mat.use_backface_culling = False
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    for node in list(nodes):
        if node.name not in {"Material Output"}:
            nodes.remove(node)

    output = nodes["Material Output"]
    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (0.90, 0.92, 0.95, 1.0)
    emission.inputs["Strength"].default_value = 1.0
    emission.location = (-120, 20)
    links.new(emission.outputs["Emission"], output.inputs["Surface"])
    return mat


def find_nonmanifold_edges(triangles):
    edge_faces = build_edge_face_map(triangles)
    return [edge for edge, faces in edge_faces.items() if len(faces) >= 3]


def build_edge_face_map(triangles):
    edge_counts = {}
    for face_idx, tri in enumerate(triangles):
        i0, i1, i2 = (int(tri[0]), int(tri[1]), int(tri[2]))
        for a, b in ((i0, i1), (i1, i2), (i2, i0)):
            edge = (a, b) if a < b else (b, a)
            edge_counts.setdefault(edge, []).append(face_idx)
    return edge_counts


def compute_face_regions(triangles, blocked_edges):
    edge_faces = build_edge_face_map(triangles)
    blocked_edges = set(blocked_edges)
    adjacency = [[] for _ in range(len(triangles))]

    for edge, faces in edge_faces.items():
        if edge in blocked_edges:
            continue
        if len(faces) != 2:
            continue
        fa, fb = faces
        adjacency[fa].append(fb)
        adjacency[fb].append(fa)

    region_ids = np.full(len(triangles), -1, dtype=np.int32)
    region_id = 0
    for start_face in range(len(triangles)):
        if region_ids[start_face] != -1:
            continue
        stack = [start_face]
        region_ids[start_face] = region_id
        while stack:
            face_idx = stack.pop()
            for nbr in adjacency[face_idx]:
                if region_ids[nbr] != -1:
                    continue
                region_ids[nbr] = region_id
                stack.append(nbr)
        region_id += 1

    if region_id == 0:
        return region_ids, 0

    counts = np.bincount(region_ids, minlength=region_id)
    order = np.argsort(-counts)
    remap = np.empty(region_id, dtype=np.int32)
    for new_id, old_id in enumerate(order):
        remap[old_id] = new_id
    return remap[region_ids], region_id


def generate_region_palette(region_count):
    curated = [
        (0.32, 0.60, 0.90, 1.0),
        (0.90, 0.44, 0.48, 1.0),
        (0.30, 0.73, 0.50, 1.0),
        (0.93, 0.74, 0.28, 1.0),
        (0.63, 0.45, 0.90, 1.0),
        (0.93, 0.58, 0.22, 1.0),
        (0.25, 0.75, 0.78, 1.0),
        (0.82, 0.30, 0.66, 1.0),
        (0.60, 0.80, 0.24, 1.0),
        (0.78, 0.30, 0.28, 1.0),
        (0.36, 0.67, 0.92, 1.0),
        (0.92, 0.66, 0.74, 1.0),
    ]
    palette = list(curated[:region_count])
    golden = 0.61803398875
    while len(palette) < region_count:
        idx = len(palette)
        hue = (0.07 + idx * golden) % 1.0
        sat = 0.66
        val = 0.99
        r, g, b = colorsys.hsv_to_rgb(hue, sat, val)
        palette.append((r, g, b, 1.0))
    return palette


def store_region_attributes(mesh_obj, face_region_ids, attr_name):
    mesh = mesh_obj.data
    if attr_name in mesh.color_attributes:
        mesh.color_attributes.remove(mesh.color_attributes[attr_name])

    color_attr = mesh.color_attributes.new(name=attr_name, type="FLOAT_COLOR", domain="CORNER")
    region_count = int(face_region_ids.max()) + 1 if len(face_region_ids) else 0
    palette = generate_region_palette(region_count)

    for poly in mesh.polygons:
        color = palette[int(face_region_ids[poly.index])]
        for loop_idx in poly.loop_indices:
            color_attr.data[loop_idx].color = color

    return region_count


def build_nonmanifold_edge_material():
    mat = bpy.data.materials.new("surface_nonmanifold_edges")
    mat.use_nodes = True
    mat.use_backface_culling = False
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    for node in list(nodes):
        if node.name not in {"Material Output"}:
            nodes.remove(node)

    output = nodes["Material Output"]

    emission = nodes.new("ShaderNodeEmission")
    emission.location = (-220, 20)
    emission.inputs["Color"].default_value = (0.93, 0.34, 0.24, 1.0)
    emission.inputs["Strength"].default_value = 1.0

    links.new(emission.outputs["Emission"], output.inputs["Surface"])
    return mat


def build_region_partition_material(color_attr_name):
    mat = bpy.data.materials.new("surface_nonmanifold_regions")
    mat.use_nodes = True
    mat.use_backface_culling = False
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    for node in list(nodes):
        if node.name not in {"Material Output"}:
            nodes.remove(node)

    output = nodes["Material Output"]

    color_attr = nodes.new("ShaderNodeAttribute")
    color_attr.attribute_name = color_attr_name
    color_attr.location = (-700, 40)

    hsv = nodes.new("ShaderNodeHueSaturation")
    hsv.location = (-450, 40)
    hsv.inputs["Saturation"].default_value = 1.0
    hsv.inputs["Value"].default_value = 1.0

    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (-120, 40)
    bsdf.inputs["Metallic"].default_value = 0.0
    bsdf.inputs["Roughness"].default_value = 0.50
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.14
    elif "Specular" in bsdf.inputs:
        bsdf.inputs["Specular"].default_value = 0.12
    if "Alpha" in bsdf.inputs:
        bsdf.inputs["Alpha"].default_value = 1.0
    if "Transmission Weight" in bsdf.inputs:
        bsdf.inputs["Transmission Weight"].default_value = 0.0
    elif "Transmission" in bsdf.inputs:
        bsdf.inputs["Transmission"].default_value = 0.0
    if "Coat Weight" in bsdf.inputs:
        bsdf.inputs["Coat Weight"].default_value = 0.0
    elif "Clearcoat" in bsdf.inputs:
        bsdf.inputs["Clearcoat"].default_value = 0.0
    if "Emission Strength" in bsdf.inputs:
        bsdf.inputs["Emission Strength"].default_value = 0.0

    links.new(color_attr.outputs["Color"], hsv.inputs["Color"])
    links.new(hsv.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    return mat


def create_nonmanifold_edge_overlay(mesh_obj, edge_pairs, radius=0.014):
    if not edge_pairs:
        return None

    mesh = mesh_obj.data
    verts = [Vector(v.co) for v in mesh.vertices]

    curve_data = bpy.data.curves.new(name="nonmanifold_edge_overlay_curve", type="CURVE")
    curve_data.dimensions = "3D"
    curve_data.fill_mode = "FULL"
    curve_data.bevel_depth = radius
    curve_data.bevel_resolution = 12
    curve_data.resolution_u = 1

    for edge_idx, (va, vb) in enumerate(edge_pairs):
        spline = curve_data.splines.new("POLY")
        spline.points.add(1)
        a = verts[va]
        b = verts[vb]
        spline.points[0].co = (a.x, a.y, a.z, 1.0)
        spline.points[1].co = (b.x, b.y, b.z, 1.0)
        spline.use_smooth = True
        spline.order_u = 1

    curve_obj = bpy.data.objects.new("nonmanifold_edge_overlay", curve_data)
    bpy.context.collection.objects.link(curve_obj)
    curve_obj.parent = mesh_obj
    curve_obj.matrix_parent_inverse = Matrix.Identity(4)

    edge_material = build_nonmanifold_edge_material()
    curve_data.materials.append(edge_material)
    curve_obj.visible_shadow = False
    curve_obj.hide_render = True
    return curve_obj


def assign_single_material(mesh_obj, material):
    mesh_obj.data.materials.clear()
    mesh_obj.data.materials.append(material)
    mesh_obj.active_material = material


def set_nonmanifold_overlay_visible(overlay_obj, visible):
    if overlay_obj is None:
        return
    overlay_obj.hide_render = not visible


def render_still(output_path):
    bpy.context.scene.render.filepath = str(output_path)
    render_start = time.perf_counter()
    bpy.ops.render.render(write_still=True)
    return time.perf_counter() - render_start


def main():
    args = parse_args()
    requested_items = set(args.items or ITEMS)
    (
        output_path,
        plain_output_path,
        nonmanifold_output_path,
        regions_output_path,
        blend_path,
        plain_blend_path,
        nonmanifold_blend_path,
        regions_blend_path,
    ) = ensure_output_paths(args)

    clear_scene()
    setup_scene(args)
    add_ground()
    camera_obj = add_camera()
    lights = add_lights()
    camera_override = load_camera_override(args.camera_override)

    if args.mesh:
        mesh_obj = import_mesh(args.mesh)
    else:
        if args.primitive == "plane":
            mesh_obj = create_plane_mesh()
        elif args.primitive == "cube":
            mesh_obj = create_cube_mesh()
        else:
            mesh_obj = create_monkey_mesh()
    prepare_mesh(mesh_obj, args.fit_size, apply_subsurf=not bool(args.mesh))

    look_target = DEFAULT_LOOK_TARGET
    fit_margin = DEFAULT_CAMERA_FIT_MARGIN
    camera_mode = "auto_fit"
    if camera_override:
        look_target = tuple(float(x) for x in camera_override.get("look_target", DEFAULT_LOOK_TARGET))
        fit_margin = float(camera_override.get("fit_margin", DEFAULT_CAMERA_FIT_MARGIN))

    if camera_override and ("position_hint" in camera_override or "view_direction" in camera_override):
        orient_camera_from_hint(
            camera_obj,
            position_hint=camera_override.get("position_hint"),
            view_direction=camera_override.get("view_direction"),
            look_target=look_target,
        )
        if "lens" in camera_override:
            camera_obj.data.lens = float(camera_override["lens"])
        fit_camera_to_mesh(camera_obj, mesh_obj, look_target=look_target, margin=fit_margin)
        camera_mode = "directional_fit_override"
    elif camera_override and apply_camera_override(camera_obj, camera_override):
        camera_mode = "exact_override"
    else:
        fit_camera_to_mesh(camera_obj, mesh_obj, look_target=look_target, margin=fit_margin)

    place_lights_relative_to_camera(lights, camera_obj, look_target=look_target)

    mesh = mesh_obj.data
    verts = np.array([tuple(v.co) for v in mesh.vertices], dtype=float)
    triangles = np.array([tuple(p.vertices) for p in mesh.polygons], dtype=int)
    nonmanifold_edges = find_nonmanifold_edges(triangles)
    face_region_ids, region_count = compute_face_regions(triangles, nonmanifold_edges)

    distances = None
    distance_path = None
    geodesic_elapsed = None
    source_idx = None
    color_attr_name = None
    line_attr_name = None
    region_attr_name = "nonmanifold_region_color"

    if "contour" in requested_items:
        if not args.distance_file:
            raise ValueError(
                "Contour generation requires --distance-file. "
                "Compute robust heat distances first with compute_heat_distances.py."
            )
        geodesic_start = time.perf_counter()
        distances, distance_path = load_precomputed_distances(args.distance_file)
        geodesic_elapsed = time.perf_counter() - geodesic_start
        if len(distances) != len(verts):
            raise ValueError(
                f"Distance count mismatch: file has {len(distances)} values but mesh has {len(verts)} vertices."
            )
        source_idx = -1
        color_attr_name = "geo_dist_color"
        line_attr_name = "geo_dist_line"
        store_distance_attributes(
            mesh_obj,
            distances,
            color_attr_name,
            line_attr_name,
            upper_percentile=args.distance_percentile,
        )
    store_region_attributes(mesh_obj, face_region_ids, region_attr_name)
    contour_material = None
    if "contour" in requested_items:
        if args.unlit:
            contour_material = build_surface_contour_unlit_material(
                color_attr_name,
                line_attr_name,
                line_density=args.line_density,
                line_width=args.line_width,
            )
        else:
            contour_material = build_surface_contour_material(
                mesh_obj,
                color_attr_name,
                line_attr_name,
                line_density=args.line_density,
                line_width=args.line_width,
            )
    if args.unlit:
        plain_material = build_plain_unlit_material()
    else:
        plain_material = build_plain_plastic_material()
    region_material = build_region_partition_material(region_attr_name)
    nonmanifold_overlay = create_nonmanifold_edge_overlay(mesh_obj, nonmanifold_edges)

    contour_render_elapsed = None
    plain_render_elapsed = None
    nonmanifold_render_elapsed = None
    regions_render_elapsed = None

    if "contour" in requested_items:
        assign_single_material(mesh_obj, contour_material)
        set_nonmanifold_overlay_visible(nonmanifold_overlay, visible=False)
        bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
        contour_render_elapsed = None if args.save_only else render_still(output_path)

    if "plastic" in requested_items:
        assign_single_material(mesh_obj, plain_material)
        set_nonmanifold_overlay_visible(nonmanifold_overlay, visible=False)
        bpy.ops.wm.save_as_mainfile(filepath=str(plain_blend_path))
        plain_render_elapsed = None if args.save_only else render_still(plain_output_path)

    if "nonmanifold_edges" in requested_items:
        assign_single_material(mesh_obj, plain_material)
        set_nonmanifold_overlay_visible(nonmanifold_overlay, visible=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(nonmanifold_blend_path))
        nonmanifold_render_elapsed = None if args.save_only else render_still(nonmanifold_output_path)

    if "nonmanifold_regions" in requested_items:
        assign_single_material(mesh_obj, region_material)
        set_nonmanifold_overlay_visible(nonmanifold_overlay, visible=False)
        bpy.ops.wm.save_as_mainfile(filepath=str(regions_blend_path))
        regions_render_elapsed = None if args.save_only else render_still(regions_output_path)

    if distance_path is not None:
        print(f"Distance mode: precomputed_file")
        print(f"Distance file: {distance_path}")
        print(f"Source vertex: {source_idx}")
        print(f"Geodesic solve time: {geodesic_elapsed:.4f} s")
    else:
        print("Distance mode: skipped")
    print(f"Camera mode: {camera_mode}")
    print(f"Camera override: {camera_override['_path'] if camera_override else 'auto_fit'}")
    print(f"Distance support vertex count: {len(verts)}")
    print(f"Distance support face count: {len(triangles)}")
    print(f"Non-manifold edge count (>=3 incident faces): {len(nonmanifold_edges)}")
    print(f"Non-manifold flood regions: {region_count}")
    print(f"Generated items: {', '.join(sorted(requested_items))}")
    if args.save_only:
        print("Render mode: save_only")
    else:
        if contour_render_elapsed is not None:
            print(f"Contour render time: {contour_render_elapsed:.4f} s")
            print(f"Saved contour image: {output_path}")
        if plain_render_elapsed is not None:
            print(f"Plain plastic render time: {plain_render_elapsed:.4f} s")
            print(f"Saved plain image: {plain_output_path}")
        if nonmanifold_render_elapsed is not None:
            print(f"Non-manifold render time: {nonmanifold_render_elapsed:.4f} s")
            print(f"Saved non-manifold image: {nonmanifold_output_path}")
        if regions_render_elapsed is not None:
            print(f"Region render time: {regions_render_elapsed:.4f} s")
            print(f"Saved region image: {regions_output_path}")
    if "contour" in requested_items:
        print(f"Saved contour scene: {blend_path}")
    if "plastic" in requested_items:
        print(f"Saved plain scene: {plain_blend_path}")
    if "nonmanifold_edges" in requested_items:
        print(f"Saved non-manifold scene: {nonmanifold_blend_path}")
    if "nonmanifold_regions" in requested_items:
        print(f"Saved region scene: {regions_blend_path}")


if __name__ == "__main__":
    main()
