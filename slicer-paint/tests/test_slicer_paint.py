"""Pruebas sin slicers; las que usan los slicers reales están en spikes/verify_slicers.py."""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
import pytest
import trimesh
from probeta import OVERHANG_DEG, cylinder_back_mask, probeta, side_overhang_masks

from slicer_paint import cli, mesh_io, orient, paint, plate, project, selection
from slicer_paint.gcode import analyze, seam_angles
from slicer_paint.reader import read_painted
from slicer_paint.selector import (MAX_DEPTH, MIXED, Capsule, Node, decode, encode, leaves,
                                   overlaps_box, paint_box, paint_region, PaintLayer, triangle_area)
from slicer_paint.writer import BLOCK, ENFORCE, NONE, PlateObject, write_3mf, write_plate


def test_auto_orient_rests_on_floor_and_reduces_overhang():
    # De pie, la T vuela 60° a ambos lados; girada, esos voladizos desaparecen.
    mesh = probeta()
    before = orient.evaluate(mesh, np.eye(3), 45)
    chosen = orient.auto_orient(mesh, 45)
    oriented = orient.apply_rotation(mesh, chosen.rotation)
    assert oriented.vertices[:, 2].min() == pytest.approx(0.0)
    assert chosen.overhang_area < before.overhang_area
    assert chosen.score < before.score


def test_overhang_counts_a_sloped_lowest_face():
    # Un cono invertido apoya en su punta: sus caras vuelan aunque sean las más bajas.
    cone = trimesh.creation.cone(radius=20, height=10, sections=32)
    inverted = orient.apply_rotation(cone, np.diag([1.0, -1.0, -1.0]))
    assert orient.evaluate(inverted, np.eye(3), 45).overhang_area > 0


def test_auto_orient_lays_a_plate_flat():
    plate = trimesh.creation.box(extents=(60, 40, 3))
    standing = orient.apply_rotation(plate, orient.rotation_to_down(np.array([1.0, 0, 0])))
    chosen = orient.auto_orient(standing)
    result = orient.apply_rotation(standing, chosen.rotation)
    assert result.extents[2] == pytest.approx(3.0)
    assert chosen.contact_area == pytest.approx(60 * 40)


def test_manual_orientation_puts_the_chosen_face_on_the_bed():
    box = trimesh.creation.box(extents=(10, 20, 30))
    chosen = orient.parse_orientation("face:+y", box)
    result = orient.apply_rotation(box, chosen.rotation)
    assert result.extents[2] == pytest.approx(20.0)
    assert result.vertices[:, 2].min() == pytest.approx(0.0)
    with pytest.raises(ValueError):
        orient.parse_orientation("face:arriba", box)


def test_rotation_keeps_triangle_order():
    mesh = probeta()
    result = orient.apply_rotation(mesh, orient.rotation_to_down(np.array([0.0, 1.0, 0.0])))
    assert np.array_equal(result.faces, mesh.faces)


def test_support_overhang_threshold_uses_known_angles():
    mesh = probeta()
    left, right = side_overhang_masks(mesh)
    # La probeta vuela 60°: entra con un límite de 45° y no con uno de 70°.
    state = paint.paint_supports(mesh, 45.0).face_states()
    assert np.all(state[left | right] == ENFORCE)
    state = paint.paint_supports(mesh, OVERHANG_DEG + 10).face_states()
    assert np.all(state[left | right] == NONE)


def test_support_ignores_the_face_on_the_bed():
    box = trimesh.creation.box(extents=(10, 10, 10))
    box.apply_translation([0, 0, 5])
    assert not paint.paint_supports(box, 45.0).is_painted()


def test_block_wins_over_enforce():
    mesh = probeta()
    left, right = side_overhang_masks(mesh)
    box = (np.array([0.0, -50, -50]), np.array([60.0, 50, 100]))
    state = paint.paint_supports(mesh, 45.0, block_boxes=[box]).face_states()
    assert np.all(state[right] == BLOCK)
    assert np.all(state[left] == ENFORCE)


def test_seam_back_only_marks_walls_facing_plus_y():
    mesh = probeta()
    state = paint.paint_seam(mesh, "back").face_states()
    painted = state == ENFORCE
    assert painted.any()
    assert np.all(mesh.face_normals[painted, 1] > 0.8)
    assert np.all(np.abs(mesh.face_normals[painted, 2]) < 0.4)
    assert (state[cylinder_back_mask(mesh)] == ENFORCE).all()
    with pytest.raises(ValueError):
        paint.paint_seam(mesh, "delante")


def test_written_file_preserves_paint_and_position(tmp_path):
    mesh = probeta()
    left, right = side_overhang_masks(mesh)
    support = np.full(len(mesh.faces), NONE)
    support[left], support[right] = ENFORCE, BLOCK
    seam = np.full(len(mesh.faces), NONE)
    seam[cylinder_back_mask(mesh)] = ENFORCE
    path = tmp_path / "p.3mf"
    write_3mf(path, mesh.vertices, mesh.faces, support, seam,
              object_settings={"enable_support": "1"})
    [read] = read_painted(path)
    assert sorted(i for i, v in read.paint["paint_supports"].items() if v == "4") == list(np.flatnonzero(left))
    assert sorted(i for i, v in read.paint["paint_supports"].items() if v == "8") == list(np.flatnonzero(right))
    assert sorted(read.paint["paint_seam"]) == list(np.flatnonzero(seam))
    assert (read.vertices.min(axis=0)[:2] + read.vertices.max(axis=0)[:2]) / 2 == pytest.approx([128, 128])
    assert read.vertices[:, 2].min() == pytest.approx(0.0, abs=1e-5)


def test_written_file_has_no_application_metadata(tmp_path):
    # Declarar Application hace que Orca rechace el archivo: ver writer.py.
    mesh = trimesh.creation.box(extents=(10, 10, 10))
    path = tmp_path / "b.3mf"
    write_3mf(path, mesh.vertices, mesh.faces, object_settings={"enable_support": "1"})
    with zipfile.ZipFile(path) as z:
        assert b'name="Application"' not in z.read("3D/3dmodel.model")
        for name in z.namelist():
            if name.endswith((".model", ".rels", ".config", ".xml")):
                ET.fromstring(z.read(name))
        settings = z.read("Metadata/model_settings.config").decode()
    assert 'key="enable_support" value="1"' in settings


def test_clean_removes_degenerate_faces():
    vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [2, 0, 0]], dtype=float)
    faces = np.array([[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3], [0, 1, 4]])
    assert len(mesh_io.clean(vertices, faces).faces) == 4


def test_cli_generates_file_with_support_settings(tmp_path, capsys):
    stl = tmp_path / "t.stl"
    probeta().export(stl)
    out = tmp_path / "sub" / "t.3mf"
    code = cli.main([str(stl), "-o", str(out), "--orient", "none", "--support-overhang", "45",
                     "--seam", "back"])
    assert code == 0
    [read] = read_painted(out)
    assert "paint_supports" in read.paint and "paint_seam" in read.paint
    with zipfile.ZipFile(out) as z:
        assert 'value="normal(manual)"' in z.read("Metadata/model_settings.config").decode()
    assert "estanca" in capsys.readouterr().out


def test_cli_reports_bad_input(tmp_path, capsys):
    code = cli.main([str(tmp_path / "no.stl"), "-o", str(tmp_path / "x.3mf")])
    assert code == 2
    assert "Error" in capsys.readouterr().err


def test_gcode_analysis_finds_support_and_seam():
    gcode = """; FEATURE: Support
G1 X10 Y10 Z0.2 F600
G1 X20 Y10 E1
; FEATURE: Outer wall
G1 X30 Y38 F600
G1 X32 Y30 E1
G1 X30 Y22 E1
"""
    report = analyze(gcode)
    assert report.points("support").tolist() == [[20, 10, 0.2]]
    assert report.outer_wall_starts == [(30, 38, 0.2)]
    assert seam_angles(report, (30, 30), 8) == pytest.approx([90.0])


DEMO = Path(r"C:\wormgear\demo\3d files\WormGear.3mf")
SQUARE_A = np.array([[0.0, 0, 0], [40, 0, 0], [40, 40, 0]])
SQUARE_B = np.array([[0.0, 0, 0], [40, 40, 0], [0, 40, 0]])


def _box(*values):
    corners = np.array(values, dtype=float).reshape(2, 3)
    return corners[0], corners[1]


def _painted_area(triangle, node, state=ENFORCE):
    return sum(triangle_area(t) for t, s in leaves(triangle, node) if s == state)


def test_whole_triangle_strings_match_the_format():
    assert encode(Node(state=ENFORCE)) == "4"
    assert encode(Node(state=BLOCK)) == "8"
    assert decode("4").state == ENFORCE
    assert decode("8").state == BLOCK


def test_split_string_puts_the_root_last_and_children_reversed():
    node = Node(sides=3, children=[Node(state=ENFORCE), Node(), Node(state=BLOCK), Node()])
    # Flujo: raíz 3, hijo 3 (0), hijo 2 (8), hijo 1 (0), hijo 0 (4); la cadena va al revés.
    assert encode(node) == "40803"
    assert encode(decode("40803")) == "40803"


@pytest.mark.parametrize("text", ["", "3", "03", "44"])
def test_decode_rejects_malformed_strings(text):
    with pytest.raises(ValueError):
        decode(text)


@pytest.mark.skipif(not DEMO.exists(), reason="falta la demo de WormGear")
def test_real_strings_survive_decode_and_encode():
    with zipfile.ZipFile(DEMO) as z:
        data = z.read("3D/Objects/object_16.model").decode()
    strings = re.findall(r'paint_seam="([^"]*)"', data)
    assert strings
    assert all(encode(decode(s)) == s for s in strings)


def test_box_paints_the_analytic_area_within_resolution():
    box = _box(10, 10, -1, 25, 30, 1)
    resolution = 0.25
    area = 0.0
    for triangle in (SQUARE_A, SQUARE_B):
        node = paint_box(Node(), triangle, box, ENFORCE, resolution)
        area += _painted_area(triangle, node)
        for leaf, state in leaves(triangle, node):
            if state == ENFORCE:
                assert np.all(leaf >= box[0] - resolution - 1e-9)
                assert np.all(leaf <= box[1] + resolution + 1e-9)
    # El error se limita a una franja de la resolución a lo largo del perímetro.
    assert area == pytest.approx(15 * 20, abs=resolution * 2 * (15 + 20))


def test_box_covering_a_triangle_leaves_a_single_leaf():
    node = paint_box(Node(), SQUARE_A, _box(-1, -1, -1, 50, 50, 1), ENFORCE)
    assert not node.is_split and node.state == ENFORCE


def test_box_away_from_a_triangle_changes_nothing():
    original = Node(state=BLOCK)
    assert paint_box(original, SQUARE_A, _box(100, 100, -1, 110, 110, 1), ENFORCE) is original


def test_box_touching_an_edge_does_not_paint():
    box = _box(40, 0, -1, 50, 40, 1)
    assert not overlaps_box(SQUARE_A, box)
    assert encode(paint_box(Node(), SQUARE_A, box, ENFORCE)) == "0"


def test_depth_limit_bounds_the_tree():
    def depth(node):
        return 1 + max(map(depth, node.children)) if node.is_split else 0

    node = paint_box(Node(), SQUARE_A * 100, _box(1000, 1000, -1, 1010, 1010, 1), ENFORCE, 0.001)
    assert depth(node) <= MAX_DEPTH


def test_block_over_enforce_on_part_of_a_triangle():
    node = paint_box(Node(state=ENFORCE), SQUARE_A, _box(20, -1, -1, 50, 50, 1), BLOCK, 0.25)
    assert _painted_area(SQUARE_A, node, BLOCK) > 0
    assert _painted_area(SQUARE_A, node, ENFORCE) > 0
    total = _painted_area(SQUARE_A, node, BLOCK) + _painted_area(SQUARE_A, node, ENFORCE)
    assert total == pytest.approx(triangle_area(SQUARE_A))
    assert encode(decode(encode(node))) == encode(node)


def test_support_boxes_leave_walls_and_roofs_alone():
    mesh = probeta()
    left, right = side_overhang_masks(mesh)
    layer = paint.paint_supports(mesh, block_boxes=[_box(0, -50, -1, 60, 50, 60)])
    assert set(layer.nodes) == set(np.flatnonzero(right))
    assert not (set(layer.nodes) & set(np.flatnonzero(left)))


def test_support_box_splits_only_where_it_crosses_the_border():
    mesh = probeta()
    left, _ = side_overhang_masks(mesh)
    layer = paint.paint_supports(mesh, enforce_boxes=[_box(-60, 0, -1, 0, 50, 60)])
    states = layer.face_states()
    assert np.any(states[left] == MIXED)
    expected = mesh.area_faces[left].sum() / 2
    assert layer.areas(mesh.triangles)[ENFORCE] == pytest.approx(expected, rel=0.05)


def test_seam_box_only_paints_walls():
    mesh = probeta()
    layer = paint.paint_seam(mesh, "box:-3,9,2,3,11,18")
    assert layer.is_painted()
    assert np.all(np.abs(mesh.face_normals[list(layer.nodes), 2]) < 0.4)
    assert layer.areas(mesh.triangles)[ENFORCE] == pytest.approx(6 * 16, rel=0.05)


def test_partial_paint_is_written_and_read_back(tmp_path):
    mesh = probeta()
    layer = paint.paint_supports(mesh, enforce_boxes=[_box(-60, 0, -1, 0, 50, 60)])
    path = tmp_path / "p.3mf"
    write_3mf(path, mesh.vertices, mesh.faces, layer)
    [read] = read_painted(path)
    strings = read.paint["paint_supports"]
    assert strings == {i: layer.string(i) for i in layer.nodes}
    assert any(len(s) > 1 for s in strings.values())


def _read_entry(path, name):
    with zipfile.ZipFile(path) as z:
        return z.read(name).decode() if name in z.namelist() else None


def test_bambu_target_carries_project_and_application(tmp_path):
    stl = tmp_path / "t.stl"
    probeta().export(stl)
    out = tmp_path / "b.3mf"
    assert cli.main([str(stl), "-o", str(out), "--orient", "none", "--target", "bambu",
                     "--support-overhang", "45"]) == 0
    assert _read_entry(out, project.PROJECT_FILE).encode() == project.DEFAULT_TEMPLATE.read_bytes()
    main = _read_entry(out, "3D/3dmodel.model")
    assert '<metadata name="Application">BambuStudio-02.08.02.60</metadata>' in main
    assert 'key="enable_support" value="1"' in _read_entry(out, "Metadata/model_settings.config")


def test_template_passes_the_check_of_the_installed_bambu():
    # Sin nozzle_diameter ni printer_model, Bambu borra los ajustes por objeto: ver project.py.
    settings = json.loads(project.load_project_settings())
    assert settings["printer_model"] == "Bambu Lab P1S"
    assert settings["nozzle_diameter"] == ["0.4"]


def test_orca_target_stays_free_of_project_settings(tmp_path):
    stl = tmp_path / "t.stl"
    probeta().export(stl)
    out = tmp_path / "o.3mf"
    assert cli.main([str(stl), "-o", str(out), "--orient", "none"]) == 0
    assert _read_entry(out, project.PROJECT_FILE) is None
    assert 'name="Application"' not in _read_entry(out, "3D/3dmodel.model")


def test_project_settings_are_read_from_a_project_file(tmp_path):
    settings = project.DEFAULT_TEMPLATE.read_bytes()
    source = tmp_path / "otro.3mf"
    with zipfile.ZipFile(source, "w") as z:
        z.writestr(project.PROJECT_FILE, settings)
    assert project.load_project_settings(source) == settings
    empty = tmp_path / "vacio.3mf"
    with zipfile.ZipFile(empty, "w") as z:
        z.writestr("a.txt", "x")
    with pytest.raises(ValueError):
        project.load_project_settings(empty)


def _save_in_slicer(path, slicer):
    """Imita guardar el 3MF en el laminador tras cambiar opciones: proyecto, objeto y placa.
    Orca escribe la misma Application que Bambu y además su metadata OrcaSlicer (repetida)."""
    settings = json.loads(project.DEFAULT_TEMPLATE.read_bytes())
    settings["wall_loops"] = "5"
    entries = {}
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            entries[name] = z.read(name)
    meta = ' <metadata name="Application">BambuStudio-02.08.01.55</metadata>\n'
    if slicer == "orca":
        meta += ' <metadata name="OrcaSlicer">2.5.0-dev</metadata>\n' * 2
    model = re.sub(r' <metadata name="Application">[^<]*</metadata>\n', "",
                   entries["3D/3dmodel.model"].decode())
    entries["3D/3dmodel.model"] = model.replace("<resources>", meta + "<resources>", 1).encode()
    entries["Metadata/model_settings.config"] = (
        entries["Metadata/model_settings.config"].decode()
        .replace('<metadata key="extruder" value="1"/>',
                 '<metadata key="extruder" value="2"/>\n    <metadata key="wall_loops" value="4"/>', 1)
        .replace('value="normal(manual)"', 'value="tree(manual)"', 1)
        .replace('<metadata key="plater_name" value=""/>',
                 '<metadata key="plater_name" value="mi placa"/>\n'
                 '    <metadata key="thumbnail_file" value="Metadata/plate_1.png"/>', 1).encode())
    entries[project.PROJECT_FILE] = json.dumps(settings).encode()
    with zipfile.ZipFile(path, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return entries[project.PROJECT_FILE]


@pytest.mark.parametrize("slicer", ["orca", "bambu"])
def test_rewriting_keeps_the_print_options_the_slicer_saved(tmp_path, slicer):
    stl = tmp_path / "t.stl"
    probeta().export(stl)
    out = tmp_path / "t.3mf"
    args = [str(stl), "-o", str(out), "--orient", "none", "--target", slicer, "--support-overhang", "45"]
    assert cli.main(args) == 0
    saved = _save_in_slicer(out, slicer)
    assert cli.main(args) == 0
    assert _read_entry(out, project.PROJECT_FILE).encode() == saved
    main = _read_entry(out, "3D/3dmodel.model")
    assert main.count('<metadata name="Application">BambuStudio-02.08.01.55</metadata>') == 1
    assert main.count('name="OrcaSlicer"') == (1 if slicer == "orca" else 0)
    root = ET.fromstring(_read_entry(out, "Metadata/model_settings.config"))
    obj = {m.get("key"): m.get("value") for m in root.find("object").findall("metadata")}
    assert obj["extruder"] == "2" and obj["wall_loops"] == "4"
    assert obj["enable_support"] == "1"            # la pintura de soportes sigue mandando
    assert obj["support_type"] == "tree(manual)"   # el tipo elegido en el laminador se queda
    plate_meta = {m.get("key"): m.get("value") for m in root.find("plate").findall("metadata")}
    assert plate_meta["plater_name"] == "mi placa" and plate_meta["plater_id"] == "1"
    assert "thumbnail_file" not in plate_meta      # las miniaturas no se copian
    # Pedir un tipo de soportes gana al guardado.
    assert cli.main(args + ["--support-mode", "auto"]) == 0
    assert 'key="support_type" value="normal(auto)"' in _read_entry(out, "Metadata/model_settings.config")


def test_fresh_or_another_slicer_discards_the_saved_print_options(tmp_path, capsys):
    stl = tmp_path / "t.stl"
    probeta().export(stl)
    out = tmp_path / "t.3mf"
    assert cli.main([str(stl), "-o", str(out), "--orient", "none"]) == 0
    _save_in_slicer(out, "orca")
    assert cli.main([str(stl), "-o", str(out), "--orient", "none", "--fresh"]) == 0
    assert _read_entry(out, project.PROJECT_FILE) is None
    assert 'key="wall_loops"' not in _read_entry(out, "Metadata/model_settings.config")
    _save_in_slicer(out, "orca")
    capsys.readouterr()
    assert cli.main([str(stl), "-o", str(out), "--orient", "none", "--target", "bambu"]) == 0
    assert "se guardó con orca" in capsys.readouterr().err
    assert _read_entry(out, project.PROJECT_FILE).encode() == project.DEFAULT_TEMPLATE.read_bytes()
    assert project.read_previous(tmp_path / "no.3mf") is None


def test_cli_rejects_contradictory_targets(tmp_path, capsys):
    stl = tmp_path / "t.stl"
    probeta().export(stl)
    out = str(tmp_path / "x.3mf")
    assert cli.main([str(stl), "-o", out, "--target", "orca", "--open", "bambu"]) == 2
    assert cli.main([str(stl), "-o", out, "--project-settings", "a.config"]) == 2
    assert "Error" in capsys.readouterr().err


# Costura en una arista elegida en Fusion.
def _prism():
    """Prisma hexagonal de 20 mm entre caras y 24 de alto, con un vértice en -Y."""
    prism = trimesh.creation.cylinder(radius=10 / np.cos(np.radians(30)), height=24, sections=6)
    prism.apply_transform(trimesh.transformations.rotation_matrix(np.radians(30), [0, 0, 1]))
    prism.apply_translation((0, 0, 12))
    return prism


_PRISM_EDGE = np.array([[0.0, -10 / np.cos(np.radians(30)), 0.0],
                        [0.0, -10 / np.cos(np.radians(30)), 24.0]])


def test_capsule_distance_to_polyline():
    capsule = Capsule(np.array([[0.0, 0, 0], [10, 0, 0], [10, 10, 0]]), 1.0)
    points = np.array([[5.0, 2, 0], [12, 5, 0], [-3, 0, 4], [10, 0, 0]])
    assert capsule.distance(points) == pytest.approx([2, 2, 5, 0])


def test_batch_painting_matches_painting_one_by_one():
    # apply_region pinta todo a la vez (paint_leaves) y mide la hélice solo en los tramos
    # cercanos; tiene que dar los mismos árboles que paint_region triángulo a triángulo.
    mesh = trimesh.creation.cylinder(radius=8, height=30, sections=24)
    angle = np.linspace(0, 4 * np.pi, 120)   # más tramos que _FEW_SEGMENTS: usa el árbol
    helix = np.column_stack([8 * np.cos(angle), 8 * np.sin(angle), np.linspace(-14, 14, 120)])
    capsule = Capsule(helix, 0.5)
    mask = np.ones(len(mesh.faces), dtype=bool)
    layer = PaintLayer(len(mesh.faces))
    layer.apply_region(mesh.triangles, mask, capsule, ENFORCE, 2.0)
    expected = {}
    for i, tri in enumerate(mesh.triangles):
        node = paint_region(Node(), tri, Capsule(helix, 0.5), ENFORCE, 2.0)
        if node.is_split or node.state != NONE:
            expected[i] = encode(node)
    assert expected and {i: encode(n) for i, n in layer.nodes.items()} == expected
    assert any(n.is_split for n in layer.nodes.values())


def _paint(mesh, chosen, state=ENFORCE, radius=1.0):
    layer = PaintLayer(len(mesh.faces))
    warnings = paint.paint_selection(layer, mesh, chosen, state, radius)
    return layer, warnings


def test_edge_seam_paints_a_strip_on_both_faces():
    mesh = _prism()
    layer, warnings = _paint(mesh, selection.Selection(edges=[_PRISM_EDGE]))
    assert warnings == []
    assert layer.areas(mesh.triangles)[ENFORCE] == pytest.approx(2 * 24, rel=0.1)
    painted = np.array([leaf.mean(axis=0) for i, node in layer.nodes.items()
                        for leaf, state in leaves(mesh.triangles[i], node) if state == ENFORCE])
    assert Capsule(_PRISM_EDGE, 1.0).distance(painted).max() < 1.1
    assert np.all(np.abs(mesh.face_normals[list(layer.nodes), 2]) < 0.5)


def test_edge_seam_rejects_an_edge_outside_the_mesh():
    far = _PRISM_EDGE + (0, -5, 0)
    with pytest.raises(ValueError, match="mm de la malla"):
        _paint(_prism(), selection.Selection(edges=[far]))


def _top_edge(mesh):
    corners = mesh.vertices[np.isclose(mesh.vertices[:, 2], 24.0)]
    return corners[np.linalg.norm(corners[:, :2], axis=1) > 1][:2]


def test_edge_seam_rejects_a_horizontal_edge_only_when_forcing():
    mesh = _prism()
    with pytest.raises(ValueError, match="horizontal"):
        _paint(mesh, selection.Selection(edges=[_top_edge(mesh)]))
    layer, _ = _paint(mesh, selection.Selection(edges=[_top_edge(mesh)]), BLOCK)
    assert layer.areas(mesh.triangles)[BLOCK] > 0


def test_edge_seam_warns_about_a_nearly_horizontal_edge():
    # Una rampa de 5° con caras laterales: la arista sube poco.
    ramp = trimesh.creation.box(extents=(60, 20, 20))
    shear = np.eye(4)
    shear[2, 0] = np.tan(np.radians(5))
    ramp.apply_transform(shear)
    edge = np.array([[-30.0, 10, 10 - 30 * shear[2, 0]], [30.0, 10, 10 + 30 * shear[2, 0]]])
    _, warnings = _paint(ramp, selection.Selection(edges=[edge]))
    assert len(warnings) == 1 and "5°" in warnings[0]


def _side_face(sections: int, radius=10.0, height=20.0) -> selection.Face:
    """Cara lateral de un cilindro, con otra malla que la del STL, como la daría Fusion."""
    fine = trimesh.creation.cylinder(radius=radius, height=height, sections=sections)
    side = np.abs(fine.face_normals[:, 2]) < 0.5
    return selection.Face(fine.vertices, fine.faces[side], 2 * np.pi * radius * height)


def test_face_is_recognised_with_a_different_tessellation():
    stl = trimesh.creation.cylinder(radius=10, height=20, sections=48)
    mask = paint.face_mask(stl, _side_face(200))
    assert np.array_equal(mask, np.abs(stl.face_normals[:, 2]) < 0.5)


def test_face_of_a_prism_paints_only_that_side():
    mesh = _prism()
    side = np.flatnonzero(np.isclose(mesh.face_normals[:, 0], 1, atol=1e-6) & (mesh.face_normals[:, 2] == 0))
    # La misma cara, más dividida, como la malla de Fusion.
    vertices, triangles = trimesh.remesh.subdivide_to_size(mesh.vertices, mesh.faces[side], 3.0)
    face = selection.Face(vertices, triangles, float(mesh.area_faces[side].sum()))
    layer, warnings = _paint(mesh, selection.Selection(faces=[face]), BLOCK)
    assert warnings == []
    assert sorted(layer.nodes) == sorted(side.tolist())
    assert layer.areas(mesh.triangles)[BLOCK] == pytest.approx(face.area)


def test_face_outside_the_mesh_is_an_error():
    face = _side_face(64)
    face.vertices = face.vertices + (100, 0, 0)
    with pytest.raises(ValueError, match="no está sobre la malla"):
        _paint(trimesh.creation.cylinder(radius=10, height=20, sections=48),
               selection.Selection(faces=[face]), BLOCK)


def test_face_with_a_different_area_warns():
    face = _side_face(200, height=20.0)
    face.area *= 1.5
    _, warnings = _paint(trimesh.creation.cylinder(radius=10, height=20, sections=48),
                         selection.Selection(faces=[face]), BLOCK)
    assert len(warnings) == 1 and "mm²" in warnings[0]


def _write_selection(path, edges=(), faces=()):
    path.write_text(json.dumps({
        "edges": [np.asarray(e).tolist() for e in edges],
        "faces": [{"vertices": f.vertices.tolist(), "triangles": f.triangles.tolist(), "area": f.area}
                  for f in faces]}), encoding="utf-8")
    return path


def test_cli_edge_follows_the_orientation(tmp_path):
    stl = tmp_path / "prisma.stl"
    _prism().export(stl)
    chosen = _write_selection(tmp_path / "prisma.json", edges=[_PRISM_EDGE])
    # Girada 180° sobre X, la arista sigue vertical pero pasa a +Y.
    out = tmp_path / "p.3mf"
    assert cli.main([str(stl), "-o", str(out), "--orient", "rot:180,0,0",
                     "--seam", f"fusion:{chosen}"]) == 0
    [read] = read_painted(out)
    assert read.paint["paint_seam"]
    centers = read.vertices[read.faces[list(read.paint["paint_seam"])]].mean(axis=1)
    bed_center = (read.vertices.max(axis=0) + read.vertices.min(axis=0)) / 2
    assert centers[:, 1].mean() > bed_center[1]


def test_cli_rejects_an_edge_made_horizontal_by_the_orientation(tmp_path, capsys):
    stl = tmp_path / "prisma.stl"
    _prism().export(stl)
    chosen = _write_selection(tmp_path / "e.json", edges=[_PRISM_EDGE])
    code = cli.main([str(stl), "-o", str(tmp_path / "p.3mf"), "--orient", "rot:90,0,0",
                     "--seam", f"fusion:{chosen}"])
    assert code == 2
    assert "horizontal" in capsys.readouterr().err


def test_cli_block_wins_over_forcing(tmp_path):
    mesh = _prism()
    stl = tmp_path / "prisma.stl"
    mesh.export(stl)
    # Se fuerza la arista de -Y y se prohíben las dos caras que se juntan en ella.
    sides = np.flatnonzero((mesh.face_normals[:, 1] < -0.1) & (mesh.face_normals[:, 2] == 0))
    faces = []
    for normal in np.unique(mesh.face_normals[sides].round(6), axis=0):
        index = sides[np.all(np.isclose(mesh.face_normals[sides], normal, atol=1e-5), axis=1)]
        faces.append(selection.Face(mesh.vertices, mesh.faces[index], float(mesh.area_faces[index].sum())))
    forced = _write_selection(tmp_path / "arista.json", edges=[_PRISM_EDGE])
    blocked = _write_selection(tmp_path / "caras.json", faces=faces)
    out = tmp_path / "p.3mf"
    assert cli.main([str(stl), "-o", str(out), "--orient", "none",
                     "--seam", f"fusion:{forced}", "--seam-block", f"fusion:{blocked}"]) == 0
    [read] = read_painted(out)
    strings = read.paint["paint_seam"]
    assert sorted(strings) == sorted(sides.tolist())
    assert set(strings.values()) == {"8"}


@pytest.mark.parametrize("content", [
    '{"nada": 1}', '{"edges": []}', '{"edges": [[[1, 2, 3]]]}', "no json", "[1, 2]",
    '{"faces": [{"vertices": [[0, 0, 0]], "triangles": [[0, 1, 2]], "area": 1}]}',
    '{"faces": [{"vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]], "triangles": [[0, 1, 2]]}]}'])
def test_load_selection_rejects_bad_files(tmp_path, content):
    path = tmp_path / "e.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        selection.load_selection(path)


def test_cli_support_on_a_fusion_face_paints_only_its_downward_part(tmp_path):
    # Cono invertido: la cara lateral mira hacia abajo y la tapa de arriba, hacia arriba.
    cone = trimesh.creation.cone(radius=10, height=10, sections=48)
    cone = orient.apply_rotation(cone, np.diag([1.0, -1.0, -1.0]))
    stl = tmp_path / "cono.stl"
    cone.export(stl)
    lateral = np.abs(cone.face_normals[:, 2]) < 0.99
    whole = selection.Face(cone.vertices, cone.faces, float(cone.area))
    chosen = _write_selection(tmp_path / "cono.json", faces=[whole])
    out = tmp_path / "p.3mf"
    assert cli.main([str(stl), "-o", str(out), "--orient", "none",
                     "--support-enforce", f"fusion:{chosen}"]) == 0
    [read] = read_painted(out)
    assert sorted(read.paint["paint_supports"]) == sorted(np.flatnonzero(lateral).tolist())
    assert "enable_support" in zipfile.ZipFile(out).read("Metadata/model_settings.config").decode()


# Zonas que no son caras enteras y archivo de pieza (versión 3).
def _square_patch(center, normal, size=10.0, step=2.0) -> selection.Patch:
    """Cuadrado de superficie con esa normal, mallado como lo haría Fusion."""
    plane = trimesh.creation.box(extents=(size, size, 1e-3))
    top = plane.face_normals[:, 2] > 0.5
    vertices, triangles = trimesh.remesh.subdivide_to_size(plane.vertices, plane.faces[top], step)
    vertices[:, 2] = 0
    turn = trimesh.geometry.align_vectors([0, 0, 1], normal)[:3, :3]
    return selection.Patch(vertices @ turn.T + center, triangles)


def _painted_centers(mesh, layer, state):
    return np.array([leaf.mean(axis=0) for i, node in layer.nodes.items()
                     for leaf, s in leaves(mesh.triangles[i], node) if s == state])


def test_patch_paints_only_its_part_of_a_face():
    mesh = _prism()
    patch = _square_patch(np.array([10.0, 0, 12]), [1, 0, 0])
    layer, warnings = _paint(mesh, selection.Selection(patches=[patch]), BLOCK)
    assert warnings == []
    # 100 mm² más la franja de la tolerancia en el borde.
    assert layer.areas(mesh.triangles)[BLOCK] == pytest.approx(100, rel=0.15)
    painted = _painted_centers(mesh, layer, BLOCK)
    assert np.all(np.abs(painted[:, 0] - 10) < 1e-6)
    assert np.abs(painted[:, 1]).max() < 5.5 and np.abs(painted[:, 2] - 12).max() < 5.5


def test_patch_leaves_the_opposite_wall_of_a_thin_gap():
    # Placa de 0,15 mm: la cara de abajo está dentro de la tolerancia, pero mira al revés.
    plate = trimesh.creation.box(extents=(20, 20, 0.15))
    patch = _square_patch(np.array([0.0, 0, 0.075]), [0, 0, 1])
    layer, _ = _paint(plate, selection.Selection(patches=[patch]), BLOCK)
    assert layer.is_painted()
    assert np.all(plate.face_normals[list(layer.nodes), 2] > 0.5)


def test_patch_outside_the_mesh_is_an_error():
    patch = _square_patch(np.array([30.0, 0, 12]), [1, 0, 0])
    with pytest.raises(ValueError, match="no está sobre la malla"):
        _paint(_prism(), selection.Selection(patches=[patch]), BLOCK)


def test_orientation_by_any_normal():
    mesh = _prism()
    # La normal de una cara del prisma, sin redondear a un eje.
    normal = mesh.face_normals[(np.abs(mesh.face_normals[:, 2]) < 1e-6)
                               & (mesh.face_normals[:, 0] > 0.4) & (mesh.face_normals[:, 1] > 0.4)][0]
    chosen = orient.parse_orientation("face:" + ",".join(map(str, normal)), mesh)
    assert orient.apply_rotation(mesh, chosen.rotation).extents[2] == pytest.approx(20.0)
    with pytest.raises(ValueError):
        orient.parse_orientation("face:0,0,0", mesh)


def _patch_json(patch):
    return {"vertices": patch.vertices.tolist(), "triangles": patch.triangles.tolist()}


def _write_job(path, **content):
    path.write_text(json.dumps({"version": 3, "units": "mm", **content}), encoding="utf-8")
    return path


def test_cli_job_orients_by_the_bed_and_paints_its_zones(tmp_path):
    stl = tmp_path / "prisma.stl"
    _prism().export(stl)
    patch = _square_patch(np.array([-10.0, 0, 12]), [-1, 0, 0])
    job = _write_job(tmp_path / "pieza.json", body="Prisma", bed=[1, 0, 0],
                     seam={"block": {"patches": [_patch_json(patch)]}})
    out = tmp_path / "p.3mf"
    assert cli.main([str(stl), "-o", str(out), "--fusion", str(job)]) == 0
    [read] = read_painted(out)
    assert np.ptp(read.vertices[:, 2]) == pytest.approx(20.0)
    painted = read.paint["paint_seam"]
    assert painted
    # La cara de -X queda arriba, a 20 mm de la cama.
    assert read.vertices[read.faces[list(painted)]][:, :, 2].min() == pytest.approx(20.0, abs=1e-4)
    # --orient gana a la cama del archivo.
    assert cli.main([str(stl), "-o", str(out), "--fusion", str(job), "--orient", "none"]) == 0
    [read] = read_painted(out)
    assert np.ptp(read.vertices[:, 2]) == pytest.approx(24.0)


@pytest.mark.parametrize("content, message", [
    ({"version": 2, "edges": []}, "versión 3"),
    ({"version": 3, "seams": {}}, "claves desconocidas"),
    ({"version": 3, "seam": {"force": {}}}, "enforce y block"),
    ({"version": 3, "units": "cm", "bed": [0, 0, -1]}, "mm"),
    ({"version": 3, "bed": [0, 0]}, "dirección"),
    ({"version": 3, "seam": {"block": {"edges": []}}}, "no tiene cama"),
])
def test_job_rejects_malformed_files(tmp_path, content, message):
    path = tmp_path / "pieza.json"
    path.write_text(json.dumps(content), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        selection.load_job(path)


def test_job_file_is_not_a_selection(tmp_path):
    job = _write_job(tmp_path / "pieza.json", bed=[0, 0, -1])
    with pytest.raises(ValueError, match="--fusion"):
        selection.load_selection(job)


# Placa: varias piezas en un solo 3MF.
def _write_plate(path, parts, **extra):
    path.write_text(json.dumps({"version": 1, "units": "mm", "parts": parts, **extra}), encoding="utf-8")
    return path


def test_plate_resolves_paths_from_its_folder(tmp_path):
    folder = tmp_path / "envio"
    folder.mkdir()
    path = _write_plate(folder / "placa.json", [
        {"stl": "Caja.stl", "fusion": "Caja.json", "name": "Caja de pruebas"},
        {"stl": "sub/Tapa.stl"}])
    caja, tapa = plate.load_plate(path)
    assert caja == plate.PlatePart(folder / "Caja.stl", folder / "Caja.json", "Caja de pruebas")
    assert tapa == plate.PlatePart(folder / "sub" / "Tapa.stl", None, "Tapa")


@pytest.mark.parametrize("content, message", [
    ({"version": 2, "parts": [{"stl": "a.stl"}]}, "versión 1"),
    ({"version": 1, "parts": [{"stl": "a.stl"}], "bed": [0, 0, -1]}, "claves desconocidas"),
    ({"version": 1, "parts": [{"stl": "a.stl", "orient": "none"}]}, r"pieza 1: claves desconocidas \['orient'\]"),
    ({"version": 1, "parts": []}, "al menos una pieza"),
    ({"version": 1}, "al menos una pieza"),
    ({"version": 1, "parts": [{"stl": "a.stl"}, {"fusion": "b.json"}]}, "pieza 2: falta stl"),
    ({"version": 1, "parts": [{"stl": ""}]}, "ruta"),
    ({"version": 1, "parts": [{"stl": "a.stl", "name": ""}]}, "name"),
    ({"version": 1, "units": "cm", "parts": [{"stl": "a.stl"}]}, "mm"),
])
def test_plate_rejects_malformed_files(tmp_path, content, message):
    path = tmp_path / "placa.json"
    path.write_text(json.dumps(content), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        plate.load_plate(path)


def test_arrange_centres_a_single_part():
    centers, fits = plate.arrange([(40.0, 30.0)])
    assert centers == [pytest.approx((128.0, 128.0))]
    assert fits


def test_arrange_fills_rows_with_the_gap():
    centers, fits = plate.arrange([(100.0, 50.0), (100.0, 40.0), (100.0, 50.0)])
    assert fits
    # Dos piezas caben en la primera fila (100 + 5 + 100) y la tercera pasa a la segunda.
    assert centers[0] == pytest.approx((75.5, 155.5))
    assert centers[1] == pytest.approx((180.5, 155.5))
    assert centers[2] == pytest.approx((128.0, 100.5))
    assert centers[1][0] - centers[0][0] == pytest.approx(100 + plate.PART_GAP_MM)
    assert (centers[0][1] - 25) - (centers[2][1] + 25) == pytest.approx(plate.PART_GAP_MM)


def test_arrange_reports_parts_that_do_not_fit():
    centers, fits = plate.arrange([(100.0, 100.0)] * 9)
    assert not fits and len(centers) == 9
    # La esquina delantera izquierda de la P1S no se puede usar.
    assert not plate.arrange([(235.0, 235.0)])[1]
    assert plate.arrange([(235.0, 235.0)], excluded=None)[1]


def _settings_by_object(path):
    root = ET.fromstring(zipfile.ZipFile(path).read("Metadata/model_settings.config"))
    return {obj.get("id"): {m.get("key"): m.get("value") for m in obj.findall("metadata") if m.get("key")}
            for obj in root.findall("object")}


def test_plate_writes_one_object_per_part(tmp_path):
    a = trimesh.creation.box(extents=(30, 20, 10))
    b = trimesh.creation.cylinder(radius=8, height=25, sections=32)
    support = np.full(len(a.faces), NONE)
    support[a.face_normals[:, 2] < -0.5] = ENFORCE
    path = tmp_path / "placa.3mf"
    write_plate(path, [
        PlateObject(a.vertices, a.faces, support, name="Caja",
                    settings={"enable_support": "1"}, center=(60.0, 128.0)),
        PlateObject(b.vertices, b.faces, name="Tapa", center=(160.0, 100.0))])
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        main_model = ET.fromstring(z.read("3D/3dmodel.model"))
        rels = z.read("3D/_rels/3dmodel.model.rels").decode()
        plate_config = z.read("Metadata/model_settings.config").decode()
    assert {"3D/Objects/object_1.model", "3D/Objects/object_2.model"} <= set(names)
    assert "/3D/Objects/object_2.model" in rels
    items = [e for e in main_model.iter() if e.tag.endswith("}item")]
    assert [i.get("objectid") for i in items] == ["2", "4"]
    assert plate_config.count("<plate>") == 1 and plate_config.count("<model_instance>") == 2
    settings = _settings_by_object(path)
    assert settings["2"]["name"] == "Caja" and settings["2"]["enable_support"] == "1"
    assert settings["4"]["name"] == "Tapa" and "enable_support" not in settings["4"]
    caja, tapa = read_painted(path)
    assert "paint_supports" in caja.paint and tapa.paint == {}
    for read, center in ((caja, (60, 128)), (tapa, (160, 100))):
        assert (read.vertices.min(axis=0)[:2] + read.vertices.max(axis=0)[:2]) / 2 == pytest.approx(center)
        assert read.vertices[:, 2].min() == pytest.approx(0.0, abs=1e-5)


def test_cli_plate_paints_each_part_and_places_them_on_the_bed(tmp_path, capsys):
    cone = orient.apply_rotation(trimesh.creation.cone(radius=10, height=10, sections=48),
                                 np.diag([1.0, -1.0, -1.0]))
    cone.export(tmp_path / "Cono.stl")
    whole = {"vertices": cone.vertices.tolist(), "triangles": cone.faces.tolist(), "area": float(cone.area)}
    _write_job(tmp_path / "Cono.json", bed=[0, 0, -1], support={"enforce": {"faces": [whole]}})
    (tmp_path / "piezas").mkdir()
    _prism().export(tmp_path / "piezas" / "Prisma.stl")
    placa = _write_plate(tmp_path / "placa.json", [
        {"stl": "Cono.stl", "fusion": "Cono.json", "name": "Cono invertido"},
        {"stl": "piezas/Prisma.stl"}])
    out = tmp_path / "placa.3mf"
    assert cli.main(["--plate", str(placa), "-o", str(out), "--support-style", "tree"]) == 0
    printed = capsys.readouterr().out
    assert "Pieza 1: Cono invertido" in printed and "Pieza 2: Prisma" in printed
    assert "2 piezas" in printed
    settings = _settings_by_object(out)
    assert settings["2"]["support_type"] == "tree(manual)"
    assert "enable_support" not in settings["4"]
    cono, prisma = read_painted(out)
    assert "paint_supports" in cono.paint and "paint_supports" not in prisma.paint
    boxes = [(m.vertices.min(axis=0), m.vertices.max(axis=0)) for m in (cono, prisma)]
    for low, high in boxes:
        assert (low[:2] >= 0).all() and (high[:2] <= 256).all()
        assert low[2] == pytest.approx(0.0, abs=1e-5)
    # Una al lado de la otra, a 5 mm.
    assert boxes[1][0][0] - boxes[0][1][0] == pytest.approx(plate.PART_GAP_MM, abs=1e-4)


def test_cli_plate_error_names_the_part_and_writes_nothing(tmp_path, capsys):
    _prism().export(tmp_path / "Prisma.stl")
    (tmp_path / "Tapa.json").write_text(json.dumps({"version": 3, "bed": [0, 0]}), encoding="utf-8")
    placa = _write_plate(tmp_path / "placa.json", [
        {"stl": "Prisma.stl"}, {"stl": "Prisma.stl", "fusion": "Tapa.json", "name": "Tapa"}])
    out = tmp_path / "placa.3mf"
    assert cli.main(["--plate", str(placa), "-o", str(out)]) == 2
    assert "pieza 2 (Tapa)" in capsys.readouterr().err
    assert not out.exists()


@pytest.mark.parametrize("extra, message", [
    (["--orient", "none"], "--orient"),
    (["--part", "object_1"], "--part"),
    (["--fusion", "a.json"], "--fusion"),
    (["--seam", "back"], "--seam"),
    (["--seam-block", "box:0,0,0,1,1,1"], "--seam-block"),
    (["--support-enforce", "0,0,0,1,1,1"], "--support-enforce"),
    (["--support-block", "0,0,0,1,1,1"], "--support-block"),
    (["pieza.stl"], "quita pieza.stl"),
])
def test_cli_plate_rejects_options_of_a_single_part(tmp_path, capsys, extra, message):
    placa = _write_plate(tmp_path / "placa.json", [{"stl": "a.stl"}])
    assert cli.main(["--plate", str(placa), "-o", str(tmp_path / "p.3mf"), *extra]) == 2
    assert message in capsys.readouterr().err


def test_cli_needs_an_input_or_a_plate(tmp_path, capsys):
    assert cli.main(["-o", str(tmp_path / "p.3mf")]) == 2
    assert "--plate" in capsys.readouterr().err
