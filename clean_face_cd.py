"""
clean_face_cd.py

Per-face CD filtering: sample each triangle uniformly, remove faces where
>50% of samples are farther than threshold from GT point cloud.

Usage:
    python clean_face_cd.py \
        --mesh        meshes/.../ours_base_config.ply \
        --pointcloud  meshes/.../gt_pointcloud.ply \
        --output      meshes/.../ours_base_config_clean_face.ply \
        --threshold   0.005 \
        --samples-per-face 20
"""

import argparse
import os
import numpy as np
from plyfile import PlyData, PlyElement
from scipy.spatial import cKDTree


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--mesh",       required=True)
    p.add_argument("--pointcloud", required=True)
    p.add_argument("--output",     required=True)
    p.add_argument("--threshold",  type=float, default=0.005)
    p.add_argument("--samples-per-face", type=int, default=20)
    p.add_argument("--ratio",      type=float, default=0.5,
                   help="Delete face if more than this fraction of samples exceed threshold")
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def load_mesh(path):
    ply = PlyData.read(path)
    v = ply['vertex']
    verts = np.stack([v['x'], v['y'], v['z']], axis=1).astype(np.float64)
    faces = np.array([list(f) for f in ply['face']['vertex_indices']], dtype=np.int32)
    return verts, faces


def load_pointcloud(path):
    ply = PlyData.read(path)
    v = ply['vertex']
    return np.stack([v['x'], v['y'], v['z']], axis=1).astype(np.float64)


def write_ply(verts, faces, path):
    vert_el = PlyElement.describe(
        np.array([(v[0], v[1], v[2]) for v in verts],
                 dtype=[('x', 'f4'), ('y', 'f4'), ('z', 'f4')]),
        'vertex'
    )
    face_el = PlyElement.describe(
        np.array([(f,) for f in faces], dtype=[('vertex_indices', 'O')]),
        'face'
    )
    PlyData([vert_el, face_el], text=False).write(path)


def main():
    args = parse_args()
    rng = np.random.default_rng(args.seed)

    print(f"Loading mesh:        {args.mesh}")
    verts, faces = load_mesh(args.mesh)
    print(f"  {len(verts)} vertices, {len(faces)} faces")

    print(f"Loading point cloud: {args.pointcloud}")
    gt_pts = load_pointcloud(args.pointcloud)
    print(f"  {len(gt_pts)} points")

    print(f"Threshold: {args.threshold}, samples/face: {args.samples_per_face}, ratio: {args.ratio}")

    tree = cKDTree(gt_pts)

    # sample all faces at once
    n_faces = len(faces)
    n_samples = n_faces * args.samples_per_face
    tri_verts = verts[faces]  # (F, 3, 3)
    v0, v1, v2 = tri_verts[:, 0], tri_verts[:, 1], tri_verts[:, 2]
    e1 = v1 - v0
    e2 = v2 - v0

    # per-face samples: repeat each face samples_per_face times
    face_idx = np.repeat(np.arange(n_faces), args.samples_per_face)
    u = rng.random(n_samples)
    v = rng.random(n_samples)
    mask = u + v > 1.0
    u[mask] = 1.0 - u[mask]
    v[mask] = 1.0 - v[mask]

    samples = v0[face_idx] + e1[face_idx] * u[:, None] + e2[face_idx] * v[:, None]

    # query GT
    dists, _ = tree.query(samples, k=1, p=1)  # L1 distance
    dists = dists.reshape(n_faces, args.samples_per_face)

    # for each face, count how many samples exceed threshold
    exceed_count = (dists > args.threshold).sum(axis=1)
    exceed_ratio = exceed_count / args.samples_per_face
    keep = exceed_ratio <= args.ratio

    n_keep = keep.sum()
    n_delete = n_faces - n_keep
    print(f"\nKept: {n_keep} faces, Deleted: {n_delete} faces ({100*n_delete/n_faces:.1f}%)")

    # rebuild mesh
    kept_faces = faces[keep]
    used_verts = np.unique(kept_faces)
    old_to_new = np.zeros(len(verts), dtype=np.int32)
    old_to_new[used_verts] = np.arange(len(used_verts))
    new_verts = verts[used_verts]
    new_faces = old_to_new[kept_faces]

    print(f"Output: {len(new_verts)} vertices, {len(new_faces)} faces")
    write_ply(new_verts, new_faces, args.output)
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
