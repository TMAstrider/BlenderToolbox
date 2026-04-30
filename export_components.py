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
    # sort largest first
    components.sort(key=len, reverse=True)
    print(f"  {len(components)} components")

    for i, comp in enumerate(components):
        out = os.path.join(args.outdir, f"comp_{i:03d}_{len(comp)}faces.ply")
        nv, nf = save_component(verts, faces, comp, out)
        print(f"  [{i:03d}] {nf} faces, {nv} verts -> {os.path.basename(out)}")


if __name__ == "__main__":
    main()
