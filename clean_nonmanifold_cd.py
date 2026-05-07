"""
clean_nonmanifold_cd.py

Clean non-manifold mesh by Chamfer L1 ranking + topology-aware deletion.

Algorithm:
  1. Find non-manifold edges (>=3 incident faces).
  2. Split mesh into manifold components along non-manifold edges.
  3. For each component, uniformly sample points on faces (area-weighted),
     compute one-way Chamfer L1 distance to GT point cloud.
  4. Rank components by CD-L1 (higher = worse). Iteratively delete the worst
     component that is still adjacent to a remaining non-manifold edge.
  5. Stop when no non-manifold edges remain.

Usage:
    python clean_nonmanifold_cd.py \
        --mesh        meshes/.../ours_mls.ply \
        --pointcloud  meshes/.../gt_pointcloud.ply \
        --output      meshes/.../ours_mls_clean.ply \
        [--samples-per-face 10] [--seed 42]
"""

import argparse
import os
import numpy as np
from collections import defaultdict
from plyfile import PlyData, PlyElement
from scipy.spatial import cKDTree


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--mesh",       required=True)
    p.add_argument("--pointcloud", required=True)
    p.add_argument("--output",     required=True)
    p.add_argument("--samples-per-face", type=int, default=10,
                   help="Number of uniform samples per face for CD computation")
    p.add_argument("--export-debug", default="",
                   help="Export every component as PLY with status (kept/deleted/protected)")
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------
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


def export_component_ply(verts, faces, comp_faces, path):
    """Export a single component's faces as a PLY."""
    new_faces = faces[comp_faces]
    used = np.unique(new_faces)
    old_to_new = np.zeros(len(verts), dtype=np.int32)
    old_to_new[used] = np.arange(len(used))
    new_verts = verts[used]
    new_faces_remapped = old_to_new[new_faces]
    write_ply(new_verts, new_faces_remapped, path)


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


# ---------------------------------------------------------------------------
# Non-manifold edge detection & component splitting
# ---------------------------------------------------------------------------
def find_nonmanifold_edges(faces):
    """Return set of (v0, v1) edges shared by >= 3 faces."""
    edge_count = defaultdict(int)
    for f in faces:
        for i in range(3):
            e = tuple(sorted([f[i], f[(i + 1) % 3]]))
            edge_count[e] += 1
    return {e for e, cnt in edge_count.items() if cnt >= 3}


def split_components(faces, nm_edges):
    """BFS on faces; don't cross non-manifold edges."""
    edge_to_faces = defaultdict(list)
    for fi, f in enumerate(faces):
        for i in range(3):
            e = tuple(sorted([f[i], f[(i + 1) % 3]]))
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
                e = tuple(sorted([faces[fi][i], faces[fi][(i + 1) % 3]]))
                if e in nm_edges:
                    continue
                for nb in edge_to_faces[e]:
                    if not visited[nb]:
                        visited[nb] = True
                        q.append(nb)
        components.append(comp)

    return components


# ---------------------------------------------------------------------------
# Area-weighted uniform sampling on mesh faces
# ---------------------------------------------------------------------------
def sample_component(verts, faces, comp_faces, samples_per_face, rng):
    """Uniform area-weighted sampling on a set of faces."""
    tri_verts = verts[faces[comp_faces]]  # (F, 3, 3)
    v0, v1, v2 = tri_verts[:, 0], tri_verts[:, 1], tri_verts[:, 2]
    edges1 = v1 - v0
    edges2 = v2 - v0
    areas = 0.5 * np.linalg.norm(np.cross(edges1, edges2), axis=1)
    total_area = areas.sum()

    if total_area == 0:
        return np.zeros((0, 3), dtype=np.float64), 0.0

    n_samples = len(comp_faces) * samples_per_face
    # pick faces proportional to area
    probs = areas / total_area
    face_picks = rng.choice(len(comp_faces), size=n_samples, p=probs)

    # barycentric sampling on each picked triangle
    u = rng.random(n_samples)
    v = rng.random(n_samples)
    # if u+v > 1, reflect
    mask = u + v > 1.0
    u[mask] = 1.0 - u[mask]
    v[mask] = 1.0 - v[mask]

    p0 = v0[face_picks]
    p1 = edges1[face_picks]
    p2 = edges2[face_picks]
    samples = p0 + p1 * u[:, None] + p2 * v[:, None]

    return samples, total_area


# ---------------------------------------------------------------------------
# Chamfer L1 (one-way: component samples -> GT)
# ---------------------------------------------------------------------------
def chamfer_l1_oneway(samples, gt_pts, tree):
    if len(samples) == 0:
        return float("inf")
    dists, _ = tree.query(samples, k=1, p=1)  # p=1 = L1 (Manhattan)
    return float(dists.mean())


# ---------------------------------------------------------------------------
# Build component -> adjacent non-manifold edges mapping
# ---------------------------------------------------------------------------
def build_component_edge_map(faces, components, nm_edges):
    """Return dict: component_idx -> set of non-manifold edges it touches."""
    edge_to_comps = defaultdict(set)
    for fi, f in enumerate(faces):
        for i in range(3):
            e = tuple(sorted([f[i], f[(i + 1) % 3]]))
            edge_to_comps[e].add(fi)

    # which component does each face belong to?
    face_to_comp = np.zeros(len(faces), dtype=np.int32)
    for ci, comp in enumerate(components):
        for fi in comp:
            face_to_comp[fi] = ci

    comp_nm_edges = defaultdict(set)
    for e in nm_edges:
        comps_touching = set()
        for fi in edge_to_comps.get(e, set()):
            comps_touching.add(face_to_comp[fi])
        for ci in comps_touching:
            comp_nm_edges[ci].add(e)

    return comp_nm_edges


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    args = parse_args()
    rng = np.random.default_rng(args.seed)

    print(f"Loading mesh:        {args.mesh}")
    verts, faces = load_mesh(args.mesh)
    print(f"  {len(verts)} vertices, {len(faces)} faces")

    print(f"Loading point cloud: {args.pointcloud}")
    gt_pts = load_pointcloud(args.pointcloud)
    print(f"  {len(gt_pts)} points")

    # 1. Find non-manifold edges
    print("\n1. Finding non-manifold edges (>=3 incident faces)...")
    nm_edges = find_nonmanifold_edges(faces)
    print(f"   {len(nm_edges)} non-manifold edges")

    if not nm_edges:
        print("   No non-manifold edges — mesh is already manifold. Copying as-is.")
        write_ply(verts, faces, args.output)
        return

    # 2. Split into components
    print("\n2. Splitting into manifold components...")
    components = split_components(faces, nm_edges)
    print(f"   {len(components)} components")

    # 3. Compute Chamfer L1 per component
    print("\n3. Computing Chamfer L1 per component...")
    gt_tree = cKDTree(gt_pts)
    comp_info = []  # (cd_l1, idx, n_faces, n_verts, n_samples)

    for idx, comp in enumerate(components):
        samples, area = sample_component(verts, faces, comp, args.samples_per_face, rng)
        cd = chamfer_l1_oneway(samples, gt_pts, gt_tree)
        comp_verts = list({faces[fi][j] for fi in comp for j in range(3)})
        comp_info.append((cd, idx, len(comp), len(comp_verts), len(samples), area))
        print(f"   comp {idx:03d}: CD-L1={cd:.6f}, {len(comp)} faces, {len(comp_verts)} verts, area={area:.3f}")

    # 4. Build component -> non-manifold edges map
    print("\n4. Building component-edge adjacency...")
    comp_nm_edges = build_component_edge_map(faces, components, nm_edges)

    # 5. Rank by CD-L1 (worst = highest CD first) and iteratively delete
    print("\n5. Iterative deletion (worst CD-L1 first)...")
    comp_info.sort(key=lambda x: x[0], reverse=True)  # worst first
    deleted = set()
    protected = set()
    total_faces = len(faces)
    active_nm_edges = set(nm_edges)  # edges that are still non-manifold

    for rank, (cd, ci, nf, nv, ns, area) in enumerate(comp_info):
        if not active_nm_edges:
            break

        # protect large components (>30% of total faces)
        if nf > 0.30 * total_faces:
            protected.add(ci)
            print(f"   rank {rank:03d}: PROTECT comp {ci:03d} (CD-L1={cd:.6f}, {nf} faces, "
                  f"{100*nf/total_faces:.1f}% of total)")
            continue

        # check if this component touches any active non-manifold edge
        touches = comp_nm_edges[ci] & active_nm_edges
        if touches:
            deleted.add(ci)
            active_nm_edges -= touches
            print(f"   rank {rank:03d}: DELETE comp {ci:03d} (CD-L1={cd:.6f}, {nf} faces, "
                  f"resolves {len(touches)} NM edges)")
        else:
            print(f"   rank {rank:03d}: KEEP  comp {ci:03d} (CD-L1={cd:.6f}, {nf} faces, "
                  f"no active NM edges)")

    # 6. Rebuild mesh from kept components
    print(f"\n6. Rebuilding mesh...")
    print(f"   Protected: {len(protected)}, Deleted: {len(deleted)} / {len(components)} components")
    print(f"   Remaining NM edges: {len(active_nm_edges)}")

    kept_faces_idx = sorted(fi for ci in range(len(components)) if ci not in deleted for fi in components[ci])
    new_faces = faces[kept_faces_idx]
    used_verts = np.unique(new_faces)
    old_to_new = np.zeros(len(verts), dtype=np.int32)
    old_to_new[used_verts] = np.arange(len(used_verts))
    new_verts = verts[used_verts]
    new_faces_remapped = old_to_new[new_faces]

    print(f"   Output: {len(new_verts)} vertices, {len(new_faces_remapped)} faces")
    write_ply(new_verts, new_faces_remapped, args.output)
    print(f"   Saved: {args.output}")

    if args.export_debug:
        os.makedirs(args.export_debug, exist_ok=True)
        for cd, ci, nf, nv, ns, area in comp_info:
            if ci in protected:
                tag = "PROTECTED"
            elif ci in deleted:
                tag = "DELETED"
            else:
                tag = "KEPT"
            fname = f"comp_{ci:03d}_{tag}_CD{cd:.4f}_{nf}faces.ply"
            path = os.path.join(args.export_debug, fname)
            export_component_ply(verts, faces, components[ci], path)
        print(f"   Debug components exported to: {args.export_debug}")


if __name__ == "__main__":
    main()
