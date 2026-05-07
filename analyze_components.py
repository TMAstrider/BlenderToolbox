"""Analyze connected components of a mesh — export each component + support stats."""
import argparse
import os
from collections import defaultdict
import numpy as np
from plyfile import PlyData, PlyElement
from scipy.spatial import cKDTree


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


def find_nonmanifold_edges(faces):
    edge_count = defaultdict(int)
    for f in faces:
        for i in range(len(f)):
            e = tuple(sorted([f[i], f[(i + 1) % len(f)]]))
            edge_count[e] += 1
    return {e for e, cnt in edge_count.items() if cnt > 2}


def face_components_no_nonmanifold(faces, nonmanifold_edges):
    edge_to_faces = defaultdict(list)
    for fi, f in enumerate(faces):
        for i in range(len(f)):
            e = tuple(sorted([f[i], f[(i + 1) % len(f)]]))
            edge_to_faces[e].append(fi)

    num_faces = len(faces)
    visited = np.zeros(num_faces, dtype=bool)
    components = []

    for start in range(num_faces):
        if visited[start]:
            continue
        comp = []
        queue = [start]
        visited[start] = True
        while queue:
            fi = queue.pop()
            comp.append(fi)
            f = faces[fi]
            for i in range(len(f)):
                e = tuple(sorted([f[i], f[(i + 1) % len(f)]]))
                if e in nonmanifold_edges:
                    continue
                for nb in edge_to_faces[e]:
                    if not visited[nb]:
                        visited[nb] = True
                        queue.append(nb)
        components.append(comp)

    return components


def write_component_ply(verts, faces, comp_faces, out_path):
    new_faces = faces[comp_faces]
    used_verts = np.unique(new_faces)
    old_to_new = np.zeros(len(verts), dtype=np.int32)
    old_to_new[used_verts] = np.arange(len(used_verts))
    new_verts = verts[used_verts]
    new_faces_remapped = old_to_new[new_faces]
    vert_el = PlyElement.describe(
        np.array([(v[0], v[1], v[2]) for v in new_verts],
                 dtype=[('x', 'f4'), ('y', 'f4'), ('z', 'f4')]),
        'vertex'
    )
    face_el = PlyElement.describe(
        np.array([(f,) for f in new_faces_remapped], dtype=[('vertex_indices', 'O')]),
        'face'
    )
    PlyData([vert_el, face_el], text=False).write(out_path)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mesh", required=True)
    p.add_argument("--pointcloud", required=True)
    p.add_argument("--outdir", default="debug_components")
    p.add_argument("--threshold", type=float, default=0.004)
    p.add_argument("--min-novel-gt", type=int, default=1)
    args = p.parse_args()

    print(f"Loading mesh:        {args.mesh}")
    verts, faces = load_mesh(args.mesh)
    print(f"  {len(verts)} vertices, {len(faces)} faces")

    print(f"Loading point cloud: {args.pointcloud}")
    gt_pts = load_pointcloud(args.pointcloud)
    print(f"  {len(gt_pts)} points")

    print("Finding non-manifold edges...")
    nm_edges = find_nonmanifold_edges(faces)
    print(f"  {len(nm_edges)} non-manifold edges")

    print("Splitting into components...")
    components = face_components_no_nonmanifold(faces, nm_edges)
    components.sort(key=len, reverse=True)
    print(f"  {len(components)} components")

    print("Building GT KD-tree...")
    tree = cKDTree(gt_pts)

    model_name = os.path.splitext(os.path.basename(args.mesh))[0]
    outdir = os.path.join(args.outdir, model_name)
    os.makedirs(outdir, exist_ok=True)

    # novel-mode simulation
    covered = np.zeros(len(gt_pts), dtype=bool)
    total_gt = len(gt_pts)
    kept_by_novel = []

    print(f"\n{'#':>4s} {'faces':>8s} {'verts':>8s} {'GT_cov%':>8s} {'novel_GT':>9s} {'support%':>9s} {'novel?':>6s} {'file'}")
    print("-" * 80)

    for idx, comp in enumerate(components):
        comp_verts = list({v for fi in comp for v in faces[fi]})
        comp_verts_arr = verts[comp_verts]

        # distances to GT
        dists, _ = tree.query(comp_verts_arr, k=1)
        within = dists <= args.threshold
        support_pct = 100.0 * within.sum() / len(comp_verts)

        # novel GT coverage
        near_gt_lists = tree.query_ball_point(comp_verts_arr, r=args.threshold)
        novel = set()
        for nlist in near_gt_lists:
            for nidx in nlist:
                if not covered[nidx]:
                    novel.add(nidx)

        kept = len(novel) >= args.min_novel_gt
        if kept:
            for nidx in novel:
                covered[nidx] = True
            kept_by_novel.append(idx)

        gt_cov_pct = 100.0 * len(novel) / total_gt

        fname = f"comp_{idx:03d}_{len(comp)}faces_{support_pct:.1f}pct.ply"
        out_path = os.path.join(outdir, fname)
        write_component_ply(verts, faces, comp, out_path)

        print(f"{idx:>4d} {len(comp):>8d} {len(comp_verts):>8d} {gt_cov_pct:>7.1f}% {len(novel):>9d} {support_pct:>8.1f}% {' kept' if kept else ' REMOVED':>7s} {fname}")

    print(f"\nNovel mode would keep: {len(kept_by_novel)} / {len(components)} components")
    print(f"Total faces kept: {sum(len(components[i]) for i in kept_by_novel)} / {len(faces)}")
    print(f"Components exported to: {outdir}")


if __name__ == "__main__":
    main()
