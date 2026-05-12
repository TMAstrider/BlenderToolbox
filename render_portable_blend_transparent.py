from pathlib import Path
import argparse
import json
import sys

import bpy
from mathutils import Vector


def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    parser = argparse.ArgumentParser()
    parser.add_argument("--blend", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--ground-clearance", type=float, default=0.04)
    parser.add_argument("--hide-ground", action="store_true")
    parser.add_argument("--light-preset", choices=["keep", "original", "soft"], default="keep")
    parser.add_argument("--material-preset", choices=["keep", "redmark"], default="keep")
    parser.add_argument("--plain-color", nargs=3, type=float, default=None)
    parser.add_argument("--camera-override", default="")
    parser.add_argument("--resolution-x", type=int, default=0)
    parser.add_argument("--resolution-y", type=int, default=0)
    parser.add_argument("--save-blend", default="")
    return parser.parse_args(argv)


def mesh_world_min_z():
    min_z = None
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        if obj.name.lower().startswith("plane"):
            continue
        for corner in obj.bound_box:
            z = (obj.matrix_world @ Vector(corner)).z
            min_z = z if min_z is None else min(min_z, z)
    return min_z


def configure_transparent_output(scene):
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "16"
    scene.view_settings.view_transform = "Filmic"
    scene.view_settings.look = "None"
    scene.use_nodes = False


def adjust_ground(clearance, hide_ground):
    min_z = mesh_world_min_z()
    if min_z is None:
        return

    for obj in bpy.context.scene.objects:
        if obj.type == "MESH" and obj.name.lower().startswith("plane"):
            obj.location.z = min_z - clearance
            obj.hide_render = hide_ground
            obj.hide_viewport = hide_ground
            if hasattr(obj, "is_shadow_catcher"):
                obj.is_shadow_catcher = not hide_ground


def apply_light_preset(preset):
    if preset == "keep":
        return

    if preset == "original":
        settings = {
            "render_light_key": (1600.0, 6.0),
            "render_light_fill": (16.0, 8.6),
            "render_light_top_back": (8.0, 6.2),
            "render_light_front_left": (100.0, 4.4),
        }
    elif preset == "soft":
        settings = {
            "render_light_key": (900.0, 7.5),
            "render_light_fill": (120.0, 10.0),
            "render_light_top_back": (40.0, 7.0),
            "render_light_front_left": (60.0, 5.5),
        }
    else:
        raise ValueError(f"Unknown light preset: {preset}")

    for obj in bpy.context.scene.objects:
        if obj.type != "LIGHT":
            continue
        base_name = obj.name.split(".")[0]
        if base_name not in settings:
            continue
        energy, size = settings[base_name]
        obj.data.energy = energy
        if hasattr(obj.data, "size"):
            obj.data.size = size


def apply_plain_color(rgb):
    if rgb is None:
        return

    color = (float(rgb[0]), float(rgb[1]), float(rgb[2]), 1.0)
    for mat in bpy.data.materials:
        if not mat.use_nodes:
            continue
        if not mat.name.startswith("surface_plain_plastic"):
            continue
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        for node in nodes:
            if node.bl_idname != "ShaderNodeBsdfPrincipled":
                continue
            base = node.inputs.get("Base Color")
            if base is None:
                continue
            for link in list(base.links):
                links.remove(link)
            base.default_value = color


def build_redmark_material(attr_name="Col"):
    mat = bpy.data.materials.new("surface_redmark_preview")
    mat.use_nodes = True
    mat.use_backface_culling = False
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    for node in list(nodes):
        if node.name not in {"Material Output"}:
            nodes.remove(node)

    output = nodes["Material Output"]

    color_attr = nodes.new("ShaderNodeAttribute")
    color_attr.attribute_name = attr_name
    color_attr.location = (-980, 20)

    separate = nodes.new("ShaderNodeSeparateColor")
    separate.location = (-760, 20)

    red_minus_green = nodes.new("ShaderNodeMath")
    red_minus_green.operation = "SUBTRACT"
    red_minus_green.location = (-520, 100)

    red_mask = nodes.new("ShaderNodeMath")
    red_mask.operation = "GREATER_THAN"
    red_mask.location = (-300, 100)
    red_mask.inputs[1].default_value = 0.16

    base_rgb = nodes.new("ShaderNodeRGB")
    base_rgb.location = (-520, -90)
    base_rgb.outputs[0].default_value = (0.3082, 0.6090, 0.7405, 1.0)

    base_bc = nodes.new("ShaderNodeBrightContrast")
    base_bc.location = (-300, -90)
    base_bc.inputs["Bright"].default_value = 0.0
    base_bc.inputs["Contrast"].default_value = 0.8

    red_rgb = nodes.new("ShaderNodeRGB")
    red_rgb.location = (-300, 250)
    red_rgb.outputs[0].default_value = (0.93, 0.34, 0.24, 1.0)

    mix = nodes.new("ShaderNodeMixRGB")
    mix.blend_type = "MIX"
    mix.inputs["Fac"].default_value = 0.0
    mix.location = (-40, 50)

    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (210, 40)
    bsdf.inputs["Metallic"].default_value = 0.0
    bsdf.inputs["Roughness"].default_value = 0.56
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.28
    elif "Specular" in bsdf.inputs:
        bsdf.inputs["Specular"].default_value = 0.24
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

    links.new(color_attr.outputs["Color"], separate.inputs["Color"])
    links.new(separate.outputs["Red"], red_minus_green.inputs[0])
    links.new(separate.outputs["Green"], red_minus_green.inputs[1])
    links.new(red_minus_green.outputs[0], red_mask.inputs[0])
    links.new(base_rgb.outputs["Color"], base_bc.inputs["Color"])
    links.new(red_mask.outputs[0], mix.inputs["Fac"])
    links.new(base_bc.outputs["Color"], mix.inputs["Color1"])
    links.new(red_rgb.outputs["Color"], mix.inputs["Color2"])
    links.new(mix.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    return mat


def apply_redmark_material(attr_name="Col"):
    material = build_redmark_material(attr_name=attr_name)
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        if obj.name.lower().startswith("plane"):
            continue
        color_attrs = getattr(obj.data, "color_attributes", None)
        if color_attrs is None or attr_name not in color_attrs:
            continue
        obj.data.materials.clear()
        obj.data.materials.append(material)
        obj.active_material = material


def apply_camera_override(path):
    if not path:
        return

    camera = bpy.context.scene.camera
    if camera is None:
        return

    data = json.loads(Path(path).resolve().read_text(encoding="utf-8"))
    if "location" in data:
        camera.location = tuple(float(v) for v in data["location"])
    if "rotation_euler" in data:
        camera.rotation_mode = "XYZ"
        camera.rotation_euler = tuple(float(v) for v in data["rotation_euler"])
    if "lens" in data:
        camera.data.lens = float(data["lens"])
    if "clip_start" in data:
        camera.data.clip_start = float(data["clip_start"])
    if "clip_end" in data:
        camera.data.clip_end = float(data["clip_end"])


def apply_resolution(scene, resolution_x, resolution_y):
    if resolution_x > 0:
        scene.render.resolution_x = int(resolution_x)
    if resolution_y > 0:
        scene.render.resolution_y = int(resolution_y)


def main():
    args = parse_args()
    bpy.ops.wm.open_mainfile(filepath=str(Path(args.blend).resolve()))
    scene = bpy.context.scene
    configure_transparent_output(scene)
    adjust_ground(args.ground_clearance, args.hide_ground)
    apply_light_preset(args.light_preset)
    if args.material_preset == "redmark":
        apply_redmark_material()
    apply_plain_color(args.plain_color)
    apply_camera_override(args.camera_override)
    apply_resolution(scene, args.resolution_x, args.resolution_y)

    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(output)
    bpy.ops.render.render(write_still=True)

    if args.save_blend:
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(args.save_blend).resolve()))


if __name__ == "__main__":
    main()
