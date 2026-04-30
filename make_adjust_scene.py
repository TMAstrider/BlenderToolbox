import argparse
import os
import sys

import bpy

import blendertoolbox as bt


def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []

    parser = argparse.ArgumentParser()
    parser.add_argument("--mesh-path", required=True)
    parser.add_argument("--blend-out", default="test.blend")
    parser.add_argument("--resolution", type=int, default=1024)
    parser.add_argument("--samples", type=int, default=128)
    parser.add_argument("--location", nargs=3, type=float, default=(0.0, 0.0, -0.12))
    parser.add_argument("--rotation", nargs=3, type=float, default=(90.0, 0.0, 225.0))
    parser.add_argument("--scale", nargs=3, type=float, default=(2.3, 2.3, 2.3))
    parser.add_argument("--camera-location", nargs=3, type=float, default=(3.0, 0.0, 2.0))
    parser.add_argument("--camera-lookat", nargs=3, type=float, default=(0.0, 0.0, 0.5))
    parser.add_argument("--camera-rotation", nargs=3, type=float)
    parser.add_argument("--camera-focal-length", type=float, default=45.0)
    parser.add_argument("--recalc-normals", action="store_true")
    parser.add_argument("--mesh-rgb", nargs=3, type=float, default=(144.0/255, 210.0/255, 236.0/255))
    parser.add_argument("--light-angle", nargs=3, type=float, default=(6.0, -30.0, -155.0))
    parser.add_argument("--material", default="monotone")  # "monotone" | "ao"
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


def init_scene(args):
    # Cycles engine — matches render_eval_set.py exactly
    bt.blenderInit(args.resolution, args.resolution, args.samples, exposure=1.5, use_gpu=True)
    scene = bpy.context.scene


    # lighting
    if args.material == "ao":
        bt.setLight_ambient(color=(0.8, 0.8, 0.8, 1))
    else:
        bt.setLight_sun(tuple(args.light_angle), strength=2, shadow_soft_size=0.3)
        bt.setLight_ambient(color=(0.1, 0.1, 0.1, 1))
    bt.invisibleGround(location=(0, 0, -10), shadowBrightness=0.9)
    bt.shadowThreshold(alphaThreshold=0.05, interpolationMode="CARDINAL")

    # camera
    if args.camera_rotation is not None:
        cam = bt.setCamera_from_UI(tuple(args.camera_location), tuple(args.camera_rotation), args.camera_focal_length)
    else:
        cam = bt.setCamera(tuple(args.camera_location), tuple(args.camera_lookat), args.camera_focal_length)
    scene.camera = cam


def main():
    args = parse_args()
    mesh_path = os.path.abspath(args.mesh_path)
    blend_out = os.path.abspath(args.blend_out)

    if not os.path.exists(mesh_path):
        raise FileNotFoundError(f"Mesh not found: {mesh_path}")

    init_scene(args)

    mesh = bt.readMesh(mesh_path, tuple(args.location), tuple(args.rotation), tuple(args.scale))
    select_active(mesh)
    if args.material == "flat":
        bpy.ops.object.shade_flat()
    else:
        bpy.ops.object.shade_smooth()
    if args.recalc_normals:
        make_normals_consistent(mesh)

    # apply same material as render_eval_set.py
    mesh.data.materials.clear()
    if args.material == "ao":
        bt.setMat_ambient_occlusion(mesh, 10, 32)
    elif args.material == "ceramic":
        rgb  = args.mesh_rgb
        RGBA = (rgb[0], rgb[1], rgb[2], 1.0)
        meshC = bt.colorObj(RGBA, 0.5, 1.0, 1.0, 0.0, 0.0)
        subC  = bt.colorObj(RGBA, 0.5, 2.0, 1.0, 0.0, 1.0)
        bt.setMat_ceramic(mesh, meshC, subC)
    elif args.material == "plastic":
        rgb  = args.mesh_rgb
        RGBA = (rgb[0], rgb[1], rgb[2], 1.0)
        meshColor = bt.colorObj(RGBA, 0.5, 1.0, 1.0, 0.0, 0.0)
        bt.setMat_plastic(mesh, meshColor)
    elif args.material == "matte":
        rgb  = args.mesh_rgb
        RGBA = (rgb[0], rgb[1], rgb[2], 1.0)
        meshColor = bt.colorObj(RGBA, 0.5, 1.0, 1.0, 0.0, 0.0)
        bt.setMat_plastic(mesh, meshColor)
        mat = mesh.active_material
        mat.node_tree.nodes["Principled BSDF"].inputs['Roughness'].default_value = 1.0
        mat.node_tree.nodes["Principled BSDF"].inputs['Specular IOR Level'].default_value = 0.0
    elif args.material == "flat":
        rgb  = args.mesh_rgb
        RGBA = (rgb[0], rgb[1], rgb[2], 1.0)
        mat = bpy.data.materials.new('MeshMaterial')
        mesh.data.materials.append(mat)
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes["Principled BSDF"]
        bsdf.inputs['Base Color'].default_value = RGBA
        bsdf.inputs['Roughness'].default_value = 0.4
        bsdf.inputs['Specular IOR Level'].default_value = 0.3
    elif args.material == "flat_ao":
        rgb  = args.mesh_rgb
        RGBA = (rgb[0], rgb[1], rgb[2], 1.0)
        mat = bpy.data.materials.new('MeshMaterial')
        mesh.data.materials.append(mat)
        mat.use_nodes = True
        tree = mat.node_tree
        bsdf = tree.nodes["Principled BSDF"]
        bsdf.inputs['Roughness'].default_value = 0.5
        bsdf.inputs['Specular IOR Level'].default_value = 0.2
        hsv = tree.nodes.new('ShaderNodeHueSaturation')
        hsv.inputs['Color'].default_value = RGBA
        ao = tree.nodes.new('ShaderNodeAmbientOcclusion')
        ao.inputs['Distance'].default_value = 0.3
        ao.samples = 16
        gamma = tree.nodes.new('ShaderNodeGamma')
        gamma.inputs['Gamma'].default_value = 2.0
        mix = tree.nodes.new('ShaderNodeMixRGB')
        mix.blend_type = 'MULTIPLY'
        mix.inputs['Fac'].default_value = 1.0
        tree.links.new(hsv.outputs['Color'],   ao.inputs['Color'])
        tree.links.new(ao.outputs['Color'],    mix.inputs['Color1'])
        tree.links.new(ao.outputs['AO'],       gamma.inputs['Color'])
        tree.links.new(gamma.outputs['Color'], mix.inputs['Color2'])
        tree.links.new(mix.outputs['Color'],   bsdf.inputs['Base Color'])
    else:  # monotone
        rgb  = args.mesh_rgb
        RGBA = (rgb[0], rgb[1], rgb[2], 1.0)
        CList = [None] * 3
        CList[0] = bt.discreteColor(brightness=0.8, pos1=None, pos2=None)
        CList[1] = bt.discreteColor(brightness=0.3, pos1=0.045, pos2=0.05)
        CList[2] = bt.discreteColor(brightness=0.0, pos1=0.2,   pos2=0.4)
        meshColor       = bt.colorObj(RGBA, 0.5, 1.2, 1.0,       0.0, 0.5)
        silhouetteColor = bt.colorObj(RGBA, 0.5, 1.2, 1.0 * 0.3, 0.0, 0.5)
        bt.setMat_monotone(mesh, meshColor, CList, silhouetteColor, shadowSize=0.4)

    os.makedirs(os.path.dirname(blend_out), exist_ok=True)
    bpy.ops.wm.save_mainfile(filepath=blend_out)
    print(f"Saved adjust scene: {blend_out}")
    print(f"Mesh object: {mesh.name}")
    print(f"Location: {tuple(mesh.location)}")
    print(f"Rotation(deg): {tuple(args.rotation)}")
    print(f"Scale: {tuple(mesh.scale)}")


if __name__ == "__main__":
    main()
