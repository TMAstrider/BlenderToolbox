"""
export_components.py

Export each connected component (split along non-manifold edges) as a
separate PLY file for inspection.

Usage:
    python export_components.py \
        --mesh   path/to/ours_mls.ply \
        --outdir path/to/components/
"""

import argparse
import os
import numpy as np
from collections import defaultdict
from plyfile import PlyData, PlyElement


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--mesh",   required=True)
    p.add_argument("--outdir", required=True)
    p.add_argument("--pointcloud", default="",
                   help="Optional GT point cloud for support-rate stats")
    p.add_argument("--threshold", type=float, default=0.004,
                   help="GT distance threshold for support rate")
    return p.parse_args()


def load_mesh(path):
    ply = PlyData.read(path)
    v = ply['vertex']
    verts = np.stack([v['x'], v['y'], v['z']], axis=1).astype(np.float64)
    faces = np.array([list(f) for f in ply['face']['vertex_indices']], dtype=np.int32)
    return verts, faces


def find_nonmanifold_edges(faces):
    edge_count = defaultdict(int)
    for f in faces:
        for i in range(3):
            e = tuple(sorted([f[i], f[(i+1)%3]]))
            edge_count[e] += 1
    return {e for e, c in edge_count.items() if c > 2}


def face_components(faces, nm_edges):
    edge_to_faces = defaultdict(list)
    for fi, f in enumerate(faces):
        for i in range(3):
            e = tuple(sorted([f[i], f[(i+1)%3]]))
            edge_to_faces[e].append(fi)

    visited = np.zeros(len(faces), dtype=bool)
    components = []
    for start in range(len(faces)):
        if visited[start]:
            continue
        comp = []
        q = [start]
        visited[start] = True
        while q:
            fi = q.pop()
            comp.append(fi)
            for i in range(3):
                e = tuple(sorted([faces[fi][i], faces[fi][(i+1)%3]]))
                if e in nm_edges:
                    continue
                for nb in edge_to_faces[e]:
                    if not visited[nb]:
                        visited[nb] = True
                        q.append(nb)
        components.append(comp)
    return components


def save_component(verts, faces, face_indices, path):
    comp_faces = faces[face_indices]
    used = np.unique(comp_faces)
    old_to_new = np.zeros(len(verts), dtype=np.int32)
    old_to_new[used] = np.arange(len(used))
    new_verts = verts[used]
    new_faces = old_to_new[comp_faces]

    vert_el = PlyElement.describe(
        np.array([(v[0], v[1], v[2]) for v in new_verts],
                 dtype=[('x', 'f4'), ('y', 'f4'), ('z', 'f4')]),
        'vertex'
    )
    face_el = PlyElement.describe(
        np.array([(f,) for f in new_faces], dtype=[('vertex_indices', 'O')]),
        'face'
    )
    PlyData([vert_el, face_el], text=False).write(path)
    return len(new_verts), len(new_faces)


def main():
    args = parse_args()
    os.makedirs(args.outdir, exist_ok=True)

    print(f"Loading mesh: {args.mesh}")
    verts, faces = load_mesh(args.mesh)
    print(f"  {len(verts)} vertices, {len(faces)} faces")

    nm_edges = find_nonmanifold_edges(faces)
    print(f"  {len(nm_edges)} non-manifold edges")

    components = face_components(faces, nm_edges)
    components.sort(key=len, reverse=True)
    print(f"  {len(components)} components")

    # load pointcloud and build KD-tree if provided
    tree = None
    gt_pts = None
    if args.pointcloud:
        print(f"Loading point cloud: {args.pointcloud}")
        from scipy.spatial import cKDTree
        ply = PlyData.read(args.pointcloud)
        v = ply['vertex']
        gt_pts = np.stack([v['x'], v['y'], v['z']], axis=1).astype(np.float64)
        print(f"  {len(gt_pts)} points")
        tree = cKDTree(gt_pts)

    # novel-mode simulation
    covered = None
    total_gt = len(gt_pts) if gt_pts is not None else 0
    kept_count = 0
    kept_faces_total = 0
    if gt_pts is not None:
        covered = np.zeros(total_gt, dtype=bool)

    if tree is not None:
        print(f"\n{'#':>4s} {'faces':>8s} {'verts':>8s} {'GT_cov%':>8s} {'novel_GT':>9s} {'support%':>9s} {'novel?':>6s} {'file'}")
        print("-" * 90)

    for i, comp in enumerate(components):
        out = os.path.join(args.outdir, f"comp_{i:03d}_{len(comp)}faces.ply")
        nv, nf = save_component(verts, faces, comp, out)

        if tree is not None:
            comp_verts_idx = list({v_idx for fi in comp for v_idx in faces[fi]})
            comp_verts_arr = verts[comp_verts_idx]
            dists, _ = tree.query(comp_verts_arr, k=1)
            within = dists <= args.threshold
            support_pct = 100.0 * within.sum() / len(comp_verts_idx)

            near_gt_lists = tree.query_ball_point(comp_verts_arr, r=args.threshold)
            novel = set()
            for nlist in near_gt_lists:
                for nidx in nlist:
                    if not covered[nidx]:
                        novel.add(nidx)

            kept = len(novel) >= 1
            if kept:
                for nidx in novel:
                    covered[nidx] = True
                kept_count += 1
                kept_faces_total += len(comp)

            gt_cov_pct = 100.0 * len(novel) / total_gt
            status = " kept" if kept else " REMOVED"
            print(f"{i:>4d} {len(comp):>8d} {nv:>8d} {gt_cov_pct:>7.1f}% {len(novel):>9d} {support_pct:>8.1f}% {status:>7s} {os.path.basename(out)}")
        else:
            print(f"  [{i:03d}] {nf} faces, {nv} verts -> {os.path.basename(out)}")

    if tree is not None:
        print(f"\nNovel mode would keep: {kept_count} / {len(components)} components")
        print(f"Total faces kept: {kept_faces_total} / {len(faces)}")


if __name__ == "__main__":
    main()
