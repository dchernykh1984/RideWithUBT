"""Handing plain triangle arrays to Panda3D.

The shapes themselves are worked out in `app/world/mesh.py`, which has no
graphics in it and is tested. This module only copies those numbers into the
engine's vertex buffers, which is why it is thin enough to be read rather than
tested.
"""

from __future__ import annotations

from panda3d.core import (
    Geom,
    GeomNode,
    GeomTriangles,
    GeomVertexData,
    GeomVertexFormat,
    GeomVertexWriter,
)

from app.world.mesh import Mesh


def geom_node(mesh: Mesh, name: str) -> GeomNode:
    """A scene node holding one mesh, with texture coordinates and upward normals."""
    vertex_data = GeomVertexData(name, GeomVertexFormat.getV3n3t2(), Geom.UHStatic)
    vertex_data.setNumRows(len(mesh.vertices))
    position = GeomVertexWriter(vertex_data, "vertex")
    normal = GeomVertexWriter(vertex_data, "normal")
    texture = GeomVertexWriter(vertex_data, "texcoord")
    # A mesh that says which way it faces is lit by that; one that does not is
    # a surface to ride on, and every normal points up. Sloped track loses a
    # little shading accuracy that way and gains nothing by not.
    facing = mesh.normals or ((0.0, 0.0, 1.0),) * len(mesh.vertices)
    for (x, y, z), (u, v), (nx, ny, nz) in zip(
        mesh.vertices, mesh.tex_coords, facing, strict=True
    ):
        position.addData3(x, y, z)
        normal.addData3(nx, ny, nz)
        texture.addData2(u, v)

    triangles = GeomTriangles(Geom.UHStatic)
    for a, b, c in mesh.triangles:
        triangles.addVertices(a, b, c)

    geom = Geom(vertex_data)
    geom.addPrimitive(triangles)
    node = GeomNode(name)
    node.addGeom(geom)
    return node


def arrow_node(name: str = "arrow") -> GeomNode:
    """A flat triangle pointing along +Y, used for the junction arrow.

    Built here rather than loaded, so the frozen application carries no asset it
    could fail to find.
    """
    mesh = Mesh(
        vertices=((-1.0, -1.0, 0.0), (1.0, -1.0, 0.0), (0.0, 1.6, 0.0)),
        tex_coords=((0.0, 0.0), (1.0, 0.0), (0.5, 1.0)),
        triangles=((0, 1, 2),),
    )
    return geom_node(mesh, name)
