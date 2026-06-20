"""Процедурные примитивы (без внешних моделей-ассетов)."""

from panda3d.core import (Geom, GeomNode, GeomTriangles, GeomVertexData,
                          GeomVertexFormat, GeomVertexWriter, NodePath)


def make_box(w=1.0, d=1.0, h=1.0, color=(1, 1, 1, 1), uv_scale=0.5):
    """Куб/параллелепипед с центром в начале координат: w=X, d=Y, h=Z.

    UV-координаты считаются из мировых координат граней (× uv_scale), чтобы
    наложенная текстура ТАЙЛИЛАСЬ (повторялась) по размеру грани, а не растягивалась.
    """
    x, y, z = w / 2.0, d / 2.0, h / 2.0
    verts = [
        (-x, -y, -z), (x, -y, -z), (x, y, -z), (-x, y, -z),
        (-x, -y, z), (x, -y, z), (x, y, z), (-x, y, z),
    ]
    faces = [
        ([0, 1, 2, 3], (0, 0, -1)),
        ([7, 6, 5, 4], (0, 0, 1)),
        ([4, 5, 1, 0], (0, -1, 0)),
        ([6, 7, 3, 2], (0, 1, 0)),
        ([5, 6, 2, 1], (1, 0, 0)),
        ([7, 4, 0, 3], (-1, 0, 0)),
    ]
    fmt = GeomVertexFormat.getV3n3c4t2()
    vdata = GeomVertexData("box", fmt, Geom.UHStatic)
    vwriter = GeomVertexWriter(vdata, "vertex")
    nwriter = GeomVertexWriter(vdata, "normal")
    cwriter = GeomVertexWriter(vdata, "color")
    twriter = GeomVertexWriter(vdata, "texcoord")
    tris = GeomTriangles(Geom.UHStatic)
    idx = 0
    for quad, normal in faces:
        for vi in quad:
            vx, vy, vz = verts[vi]
            vwriter.addData3(vx, vy, vz)
            nwriter.addData3(*normal)
            cwriter.addData4(*color)
            if normal[2] != 0:        # верх/низ -> плоскость XY
                u, v = vx, vy
            elif normal[1] != 0:      # перёд/зад -> плоскость XZ
                u, v = vx, vz
            else:                     # лево/право -> плоскость YZ
                u, v = vy, vz
            twriter.addData2(u * uv_scale, v * uv_scale)
        tris.addVertices(idx, idx + 1, idx + 2)
        tris.addVertices(idx, idx + 2, idx + 3)
        idx += 4
    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode("box")
    node.addGeom(geom)
    np = NodePath(node)
    np.setTwoSided(True)
    return np
