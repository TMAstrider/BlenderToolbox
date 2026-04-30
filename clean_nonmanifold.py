"""
clean_nonmanifold.py

Split mesh into connected components along non-manifold edges,
then remove components whose vertices are far from the GT point cloud.

Usage:
    python clean_nonmanifold.py \
        --mesh        path/to/ours_mls.ply \
        --pointcloud  path/to/gt_pointcloud.ply \
        --output      path/to/ours_mls_clean.ply \
        --threshold   0.05
"""

import argparse
import numpy as np
from collections import defaultdict
from plyfile import PlyData, PlyElement
from scipy.spatial import cKDTree


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--mesh",       required=True)
    p.add_argument("--pointcloud", required=True)
    p.add_argument("--output",     required=True)
    p.add_argument("--threshold",  type=float, default=0.004,
                   help="GT distance threshold (default 0.004 ≈ 2× typical CD)")
    p.add_argument("--min-faces",  type=int,   default=0,
                   help="Also remove components with fewer than this many faces (0=disabled)")
    p.add_argument("--filter-mode", default="novel",
                   choices=["dist", "novel"],
                   help="'dist': keep if any vertex within threshold of GT (original). "
                        "'novel': greedy largest-first; keep if component adds >= --min-novel-gt "
                        "new GT points not already covered by larger kept components.")
    p.add_argument("--min-novel-gt", type=int, default=1,
                   help="Min number of new GT points a component must cover to be kept "
                        "(only used with --filter-mode novel, default 1)")
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


def find_nonmanifold_edges(faces):
    """Return set of (v0, v1) edges shared by more than 2 faces."""
    edge_count = defaultdict(int)
    for f in faces:
        for i in range(len(f)):
            e = tuple(sorted([f[i], f[(i + 1) % len(f)]]))
            edge_count[e] += 1
    return {e for e, cnt in edge_count.items() if cnt > 2}


def face_components_no_nonmanifold(faces, nonmanifold_edges):
    """
    BFS on faces. Two adjacent faces are connected only if their shared edge
    is NOT a non-manifold edge.
    """
    # build edge -> face list
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
                    continue  # don't cross non-manifold edges
                for nb in edge_to_faces[e]:
                    if not visited[nb]:
                        visited[nb] = True
                        queue.append(nb)
        components.append(comp)

    return components


def main():
    args = parse_args()

    print(f"Loading mesh:        {args.mesh}")
    verts, faces = load_mesh(args.mesh)
    print(f"  {len(verts)} vertices, {len(faces)} faces")

    print(f"Loading point cloud: {args.pointcloud}")
    gt_pts = load_pointcloud(args.pointcloud)
    print(f"  {len(gt_pts)} points")

    print("Finding non-manifold edges...")
    nm_edges = find_nonmanifold_edges(faces)
    print(f"  {len(nm_edges)} non-manifold edges found")

    print("Splitting into components along non-manifold edges...")
    components = face_components_no_nonmanifold(faces, nm_edges)
    print(f"  {len(components)} components found")

    print(f"Building GT KD-tree...")
    tree = cKDTree(gt_pts)

    # sort largest first (needed for novel mode; harmless for dist mode)
    components.sort(key=len, reverse=True)

    keep_faces = []
    kept = removed = 0

    if args.filter_mode == "novel":
        print(f"Filtering by novel GT coverage (threshold={args.threshold}, min_novel={args.min_novel_gt})...")
        covered = np.zeros(len(gt_pts), dtype=bool)
        for comp in components:
            comp_verts = list({v for fi in comp for v in faces[fi]})
            # GT points within threshold of any vertex of this component
            near_gt_lists = tree.query_ball_point(verts[comp_verts], r=args.threshold)
            novel = set()
            for idx_list in near_gt_lists:
                for idx in idx_list:
                    if not covered[idx]:
                        novel.add(idx)
            passes_min_faces = (args.min_faces == 0 or len(comp) >= args.min_faces)
            if len(novel) >= args.min_novel_gt and passes_min_faces:
                keep_faces.extend(comp)
                for idx in novel:
                    covered[idx] = True
                kept += 1
            else:
                removed += 1
    else:  # dist
        print(f"Filtering by GT distance (threshold={args.threshold})...")
        for comp in components:
            comp_verts = list({v for fi in comp for v in faces[fi]})
            dists, _ = tree.query(verts[comp_verts], k=1)
            passes_min_faces = (args.min_faces == 0 or len(comp) >= args.min_faces)
            if dists.min() <= args.threshold and passes_min_faces:
                keep_faces.extend(comp)
                kept += 1
            else:
                removed += 1

    print(f"  Kept {kept} components ({len(keep_faces)} faces), removed {removed} components")

    # rebuild mesh with only kept faces
    keep_faces = sorted(keep_faces)
    new_faces = faces[keep_faces]

    # remap vertices
    used_verts = np.unique(new_faces)
    old_to_new = np.zeros(len(verts), dtype=np.int32)
    old_to_new[used_verts] = np.arange(len(used_verts))
    new_verts = verts[used_verts]
    new_faces_remapped = old_to_new[new_faces]

    print(f"  Output: {len(new_verts)} vertices, {len(new_faces_remapped)} faces")

    # write PLY
    vert_el = PlyElement.describe(
        np.array([(v[0], v[1], v[2]) for v in new_verts],
                 dtype=[('x', 'f4'), ('y', 'f4'), ('z', 'f4')]),
        'vertex'
    )
    face_el = PlyElement.describe(
        np.array([(f,) for f in new_faces_remapped], dtype=[('vertex_indices', 'O')]),
        'face'
    )
    PlyData([vert_el, face_el], text=False).write(args.output)
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
