"""
Render all mesh files in a model directory using the same setup as default_mesh.py
(Cycles engine, plastic material, sun+ambient lighting), with mesh transform and
camera parameters extracted from an adjust .blend file.

Invoked by Blender headless:
  blender -b -P render_eval_set.py -- --model-dir <dir> --output-dir <dir> [args]

Typically called via render_from_adjust_blend.py or render_eval_batch.py.
"""
import argparse
import sys
from pathlib import Path

import bpy
import blendertoolbox as bt

MESH_EXTENSIONS = {".ply", ".obj", ".stl"}

# ---- same defaults as default_mesh.py ----
DEFAULT_RGB       = [144.0/255, 210.0/255, 236.0/255]
DEFAULT_LIGHT     = [6.0, -30.0, -155.0]
DEFAULT_SAMPLES   = 200
DEFAULT_RES       = 1024


def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    # resolution / quality
    parser.add_argument("--resolution", type=int, default=DEFAULT_RES)
    parser.add_argument("--samples",    type=int, default=DEFAULT_SAMPLES)
    # mesh transform (usually overridden from adjust blend)
    parser.add_argument("--rotation", nargs=3, type=float, default=[90.0, 0.0, 225.0])
    parser.add_argument("--scale",    nargs=3, type=float, default=[2.3,  2.3,  2.3])
    parser.add_argument("--location", nargs=3, type=float, default=[0.0,  0.0, -0.12])
    # mesh appearance
    parser.add_argument("--mesh-rgb",      nargs=3, type=float, default=DEFAULT_RGB)
    parser.add_argument("--point-size",    type=float, default=0.006)
    parser.add_argument("--recalc-normals", action="store_true")
    # lighting (default_mesh.py values)
    parser.add_argument("--light-angle",    nargs=3, type=float, default=DEFAULT_LIGHT)
    parser.add_argument("--light-strength", type=float, default=2.0)
    parser.add_argument("--light-color",    nargs=3, type=float, default=[1.0, 1.0, 1.0],
                        help="Sun light RGB color, e.g. warm 1.0 0.95 0.85")
    parser.add_argument("--ambient-strength", type=float, default=0.1,
                        help="Ambient light strength (0=dark shadows, 0.3=light shadows)")
    # camera (usually overridden from adjust blend)
    parser.add_argument("--camera-location",    nargs=3, type=float, default=[3.0, 0.0, 2.0])
    parser.add_argument("--camera-lookat",      nargs=3, type=float, default=[0.0, 0.0, 0.5])
    parser.add_argument("--camera-rotation",    nargs=3, type=float)  # degrees; overrides lookat
    parser.add_argument("--camera-focal-length", type=float, default=45.0)
    # material selection
    parser.add_argument("--engine",       default="cycles")
    parser.add_argument("--material",     default="monotone")  # "monotone" | "ao"
    parser.add_argument("--ao-distance",  type=float, default=10.0)
    parser.add_argument("--ao-samples",   type=int,   default=32)
    parser.add_argument("--workbench-light",            default="STUDIO")
    parser.add_argument("--workbench-studio-light",     default="studio.sl")
    parser.add_argument("--workbench-rotate-z",         type=float, default=0.0)
    parser.add_argument("--workbench-intensity",        type=float, default=1.0)
    parser.add_argument("--workbench-background-alpha", type=float, default=0.0)
    parser.add_argument("--workbench-background-blur",  type=float, default=0.0)
    parser.add_argument("--workbench-show-shadows",     action="store_true")
    parser.add_argument("--workbench-show-cavity",      action="store_true")
    parser.add_argument("--workbench-show-specular",    action="store_true")
    parser.add_argument("--workbench-cavity-type",      default="WORLD")
    parser.add_argument("--workbench-ridge-factor",     type=float, default=1.0)
    parser.add_argument("--workbench-valley-factor",    type=float, default=1.0)
    # white background + area light (portable_render style)
    parser.add_argument("--white-background", action="store_true",
                        help="Composite over pure white (portable_render style)")
    parser.add_argument("--light-mode", default="sun", choices=["sun", "area"],
                        help="Lighting mode: sun+ambient or quad area-light rig")
    parser.add_argument("--shading", default="smooth", choices=["smooth", "flat"],
                        help="Mesh shading mode")
    return parser.parse_args(argv)


def select_active(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def make_normals_consistent(obj):
    select_active(obj)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")


def delete_mesh_obj(obj):
    """Remove one mesh object and free orphaned data blocks."""
    mesh_data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh_data.users == 0:
        bpy.data.meshes.remove(mesh_data)
    for mat in list(bpy.data.materials):
        if mat.users == 0:
            bpy.data.materials.remove(mat)


def is_point_cloud(obj):
    """True when the imported mesh has vertices but no faces (raw point cloud PLY)."""
    return len(obj.data.polygons) == 0


def setup_scene(args):
    """One-time scene init. Returns camera."""
    bt.blenderInit(args.resolution, args.resolution, args.samples, exposure=1.5, use_gpu=True)

    if args.engine == "workbench":
        scene = bpy.context.scene
        scene.render.engine = 'BLENDER_WORKBENCH'
        shading = scene.display.shading
        shading.light = args.workbench_light
        shading.studio_light = args.workbench_studio_light
        shading.studiolight_rotate_z = args.workbench_rotate_z
        shading.studiolight_intensity = args.workbench_intensity
        shading.studiolight_background_alpha = args.workbench_background_alpha
        shading.studiolight_background_blur  = args.workbench_background_blur
        shading.show_shadows = args.workbench_show_shadows
        shading.show_cavity  = args.workbench_show_cavity
        if args.workbench_show_cavity:
            shading.cavity_type = args.workbench_cavity_type
            shading.curvature_ridge_factor  = args.workbench_ridge_factor
            shading.curvature_valley_factor = args.workbench_valley_factor
        shading.show_specular_highlight = args.workbench_show_specular
        shading.color_type = 'SINGLE'
        scene.render.film_transparent = True
    else:
        # Cycles: world + ground (before lights, so area lights aren't deleted)
        if args.light_mode == "area":
            bpy.context.scene.world.use_nodes = True
            bg = bpy.context.scene.world.node_tree.nodes.get("Background")
            if bg is not None:
                bg.inputs[0].default_value = (1.0, 1.0, 1.0, 1.0)
                bg.inputs[1].default_value = 0.10
            # ground placed after camera, computed from mesh bounds (see below)
        elif args.material == "ao":
            bt.setLight_ambient(color=(0.8, 0.8, 0.8, 1))
        else:
            bt.setLight_sun(tuple(args.light_angle), strength=args.light_strength, shadow_soft_size=0.3)
            import bpy as _bpy
            _bpy.data.lights['Sun'].node_tree.nodes["Emission"].inputs['Color'].default_value = (*args.light_color, 1.0)
            bt.setLight_ambient(color=(args.ambient_strength, args.ambient_strength, args.ambient_strength, 1))
        if args.light_mode != "area":
            bt.invisibleGround(location=(0, 0, -10), shadowBrightness=0.9)
        bt.shadowThreshold(alphaThreshold=0.05, interpolationMode="CARDINAL")
        if args.white_background:
            bpy.context.scene.render.film_transparent = True
            bpy.context.scene.render.image_settings.color_mode = 'RGBA'
            setup_white_background_compositor()
        else:
            bpy.context.scene.render.film_transparent = True
            bpy.context.scene.render.image_settings.color_mode = 'RGBA'

    # camera
    if args.camera_rotation is not None:
        cam = bt.setCamera_from_UI(
            tuple(args.camera_location),
            tuple(args.camera_rotation),
            args.camera_focal_length,
        )
    else:
        cam = bt.setCamera(
            tuple(args.camera_location),
            tuple(args.camera_lookat),
            args.camera_focal_length,
        )
    bpy.context.scene.camera = cam

    # area lights placed relative to camera (after camera exists)
    if args.engine != "workbench" and args.light_mode == "area":
        look_target = tuple(args.camera_lookat) if args.camera_rotation is None else (0.0, 0.0, 0.5)
        setup_area_lights(cam, look_target)
        bt.invisibleGround(location=(0, 0, -0.92), shadowBrightness=0.95)

    return cam


def setup_white_background_compositor():
    """Composite transparent render over pure white (Filmic-safe)."""
    scene = bpy.context.scene
    scene.use_nodes = True
    tree = scene.node_tree
    nodes = tree.nodes
    links = tree.links
    for node in list(nodes):
        nodes.remove(node)
    rl = nodes.new("CompositorNodeRLayers")
    rl.location = (-300, 0)
    white = nodes.new("CompositorNodeRGB")
    white.location = (-300, -180)
    white.outputs[0].default_value = (16.0, 16.0, 16.0, 1.0)
    ao = nodes.new("CompositorNodeAlphaOver")
    ao.location = (0, 0)
    comp = nodes.new("CompositorNodeComposite")
    comp.location = (240, 0)
    links.new(white.outputs[0], ao.inputs[1])
    links.new(rl.outputs["Image"], ao.inputs[2])
    links.new(ao.outputs["Image"], comp.inputs["Image"])


def setup_area_lights(camera_obj, look_target):
    """Quad area-light rig placed relative to camera (portable_render style)."""
    from mathutils import Vector

    rig = [
        ("key",        (-5.758, 4.784, -4.888), 1600, 6.0),
        ("fill",       (1.666, 0.801, -3.573),  16,   8.6),
        ("top_back",   (1.578, 6.019, -8.324),  8,    6.2),
        ("front_left", (-5.941, 3.710, -7.929), 100,  4.4),
    ]

    target = Vector(look_target)
    view_dir = (target - camera_obj.location).normalized()
    world_up = Vector((0.0, 0.0, 1.0))
    right = view_dir.cross(world_up)
    if right.length <= 1e-8:
        world_up = Vector((0.0, 1.0, 0.0))
        right = view_dir.cross(world_up)
    right.normalize()
    up = right.cross(view_dir).normalize()

    for name, loc, energy, size in rig:
        lx, ly, lz = loc
        world_pos = camera_obj.location + right * lx + up * ly + view_dir * (-lz)
        bpy.ops.object.light_add(type="AREA", location=world_pos)
        obj = bpy.context.object
        obj.name = f"render_light_{name}"
        obj.data.energy = energy
        obj.data.size = size
        # point light at target
        direction = target - obj.location
        obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def apply_material(obj, args):
    rgb  = args.mesh_rgb
    RGBA = (rgb[0], rgb[1], rgb[2], 1.0)
    obj.data.materials.clear()

    if is_point_cloud(obj):
        ptColor = bt.colorObj(RGBA, 0.5, 1.0, 1.0, 0.0, 0.0)
        bt.setMat_pointCloud(obj, ptColor, args.point_size)
    elif args.engine == "workbench":
        # workbench reads color from material base color
        mat = bpy.data.materials.new('MeshMaterial')
        obj.data.materials.append(mat)
        mat.use_nodes = True
        mat.node_tree.nodes["Principled BSDF"].inputs['Base Color'].default_value = RGBA
        bpy.context.scene.display.shading.single_color = (RGBA[0], RGBA[1], RGBA[2])
    elif args.material == "ao":
        bt.setMat_ambient_occlusion(obj, args.ao_distance, args.ao_samples)
    elif args.material == "ceramic":
        meshC = bt.colorObj(RGBA, 0.5, 1.0, 1.0, 0.0, 0.0)
        subC  = bt.colorObj(RGBA, 0.5, 2.0, 1.0, 0.0, 1.0)
        bt.setMat_ceramic(obj, meshC, subC)
    elif args.material == "plastic":
        meshColor = bt.colorObj(RGBA, 0.5, 1.0, 1.0, 0.0, 0.0)
        bt.setMat_plastic(obj, meshColor)
    elif args.material == "matte":
        meshColor = bt.colorObj(RGBA, 0.5, 1.0, 1.0, 0.0, 0.0)
        bt.setMat_plastic(obj, meshColor)
        # override to fully matte — no specular
        mat = obj.active_material
        mat.node_tree.nodes["Principled BSDF"].inputs['Roughness'].default_value = 1.0
        mat.node_tree.nodes["Principled BSDF"].inputs['Specular IOR Level'].default_value = 0.0
    elif args.material == "flat":
        mat = bpy.data.materials.new('MeshMaterial')
        obj.data.materials.append(mat)
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes["Principled BSDF"]
        bsdf.inputs['Base Color'].default_value = RGBA
        bsdf.inputs['Roughness'].default_value = 0.4
        bsdf.inputs['Specular IOR Level'].default_value = 0.3
    elif args.material == "flat_ao":
        mat = bpy.data.materials.new('MeshMaterial')
        obj.data.materials.append(mat)
        mat.use_nodes = True
        tree = mat.node_tree
        bsdf = tree.nodes["Principled BSDF"]
        bsdf.inputs['Roughness'].default_value = 0.5
        bsdf.inputs['Specular IOR Level'].default_value = 0.2
        # color → AO → multiply → BSDF base color
        hsv = tree.nodes.new('ShaderNodeHueSaturation')
        hsv.inputs['Color'].default_value = RGBA
        ao = tree.nodes.new('ShaderNodeAmbientOcclusion')
        ao.inputs['Distance'].default_value = 0.3
        ao.samples = 16
        gamma = tree.nodes.new('ShaderNodeGamma')
        gamma.inputs['Gamma'].default_value = 3.0
        mix = tree.nodes.new('ShaderNodeMixRGB')
        mix.blend_type = 'MULTIPLY'
        mix.inputs['Fac'].default_value = 1.0
        tree.links.new(hsv.outputs['Color'],  ao.inputs['Color'])
        tree.links.new(ao.outputs['Color'],   mix.inputs['Color1'])
        tree.links.new(ao.outputs['AO'],      gamma.inputs['Color'])
        tree.links.new(gamma.outputs['Color'],mix.inputs['Color2'])
        tree.links.new(mix.outputs['Color'],  bsdf.inputs['Base Color'])
    elif args.material == "plastic_portable":
        # replicate portable_render build_plain_plastic_material()
        mat = bpy.data.materials.new('MeshMaterial')
        obj.data.materials.append(mat)
        mat.use_nodes = True
        mat.use_backface_culling = False
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        for node in list(nodes):
            if node.name not in {"Material Output", "Principled BSDF"}:
                nodes.remove(node)
        output = nodes["Material Output"]
        bsdf = nodes["Principled BSDF"]
        hsv = nodes.new("ShaderNodeHueSaturation")
        hsv.location = (-520, 80)
        hsv.inputs["Color"].default_value = RGBA
        hsv.inputs["Hue"].default_value = 0.5
        hsv.inputs["Saturation"].default_value = 1.0
        hsv.inputs["Value"].default_value = 1.0
        bc = nodes.new("ShaderNodeBrightContrast")
        bc.location = (-280, 80)
        bc.inputs["Bright"].default_value = 0.0
        bc.inputs["Contrast"].default_value = 0.8
        bsdf.location = (-20, 30)
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
        links.new(hsv.outputs["Color"], bc.inputs["Color"])
        links.new(bc.outputs["Color"], bsdf.inputs["Base Color"])
        links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    else:  # monotone
        CList = [None] * 3
        CList[0] = bt.discreteColor(brightness=0.8, pos1=None, pos2=None)
        CList[1] = bt.discreteColor(brightness=0.3, pos1=0.045, pos2=0.05)
        CList[2] = bt.discreteColor(brightness=0.0, pos1=0.2,   pos2=0.4)
        meshColor       = bt.colorObj(RGBA, 0.5, 1.2, 1.0,       0.0, 0.5)
        silhouetteColor = bt.colorObj(RGBA, 0.5, 1.2, 1.0 * 0.3, 0.0, 0.5)
        bt.setMat_monotone(obj, meshColor, CList, silhouetteColor, shadowSize=0.4)


def main():
    args = parse_args()
    model_dir  = Path(args.model_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    mesh_files = sorted(p for p in model_dir.iterdir() if p.suffix.lower() in MESH_EXTENSIONS)
    if not mesh_files:
        print(f"[warn] No mesh files found in {model_dir}")
        return

    cam = setup_scene(args)

    for mesh_path in mesh_files:
        output_path = output_dir / (mesh_path.stem + ".png")
        print(f"[render] {mesh_path.name} -> {output_path.name}")

        mesh = bt.readMesh(
            str(mesh_path),
            tuple(args.location),
            tuple(args.rotation),
            tuple(args.scale),
        )
        select_active(mesh)

        if not is_point_cloud(mesh):
            if args.shading == "flat":
                bpy.ops.object.shade_flat()
            else:
                bpy.ops.object.shade_smooth()
            if args.recalc_normals:
                make_normals_consistent(mesh)

        apply_material(mesh, args)
        bt.renderImage(str(output_path), cam)
        delete_mesh_obj(mesh)
        print(f"[done]  {output_path.name}")


if __name__ == "__main__":
    main()
