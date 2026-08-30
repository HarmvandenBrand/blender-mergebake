import os

import bpy

from .constants import BAKE_EMIT_NODE, BAKE_TARGET_NODE, EXPORT_MESH_NAME


def _find_principled(node_tree):
    for node in node_tree.nodes:
        if node.type == 'BSDF_PRINCIPLED':
            return node
    return None


def _find_output(node_tree):
    active = next(
        (n for n in node_tree.nodes
         if n.type == 'OUTPUT_MATERIAL' and n.is_active_output),
        None
    )
    if active:
        return active
    return next((n for n in node_tree.nodes if n.type == 'OUTPUT_MATERIAL'), None)


def _new_bake_image(name, size, non_color):

    existing = bpy.data.images.get(name)
    if existing:
        bpy.data.images.remove(existing)

    image = bpy.data.images.new(
        name,
        width=size,
        height=size,
        alpha=False,
    )

    if non_color:
        image.colorspace_settings.name = 'Non-Color'

    return image


def _set_bake_target(material, image):

    node_tree = material.node_tree

    node = node_tree.nodes.get(BAKE_TARGET_NODE)
    if node is None:
        node = node_tree.nodes.new("ShaderNodeTexImage")
        node.name = BAKE_TARGET_NODE
        node.location = (-900, -500)

    node.image = image

    for other in node_tree.nodes:
        other.select = False
    node.select = True
    node_tree.nodes.active = node


def _emit_rewire(material, input_name):
    """Route a Principled input into an Emission shader so it can be baked with EMIT."""

    node_tree = material.node_tree
    principled = _find_principled(node_tree)
    output = _find_output(node_tree)

    if principled is None or output is None or input_name not in principled.inputs:
        return None

    emit = node_tree.nodes.new("ShaderNodeEmission")
    emit.name = BAKE_EMIT_NODE
    emit.location = (-300, -500)

    socket = principled.inputs[input_name]

    if socket.is_linked:
        node_tree.links.new(socket.links[0].from_socket, emit.inputs["Color"])
    else:
        value = socket.default_value
        try:
            emit.inputs["Color"].default_value = (value, value, value, 1.0)
        except TypeError:
            emit.inputs["Color"].default_value = value

    surface = output.inputs["Surface"]
    previous = surface.links[0].from_socket if surface.is_linked else None

    node_tree.links.new(emit.outputs["Emission"], surface)

    return (emit, output, previous)


def _emit_restore(material, state):

    if state is None:
        return

    emit, output, previous = state
    node_tree = material.node_tree

    if previous is not None:
        node_tree.links.new(previous, output.inputs["Surface"])

    node_tree.nodes.remove(emit)


def _ensure_uv_atlas(context, obj, margin):

    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    context.view_layer.objects.active = obj

    # Drop the original per-object UV maps so the atlas is the only channel that
    # exports (glTF samples via the active-render UV map, which Godot reads as UV0).
    while obj.data.uv_layers:
        obj.data.uv_layers.remove(obj.data.uv_layers[0])

    uv = obj.data.uv_layers.new(name="ExportAtlas")
    obj.data.uv_layers.active = uv
    uv.active_render = True

    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=1.15192, island_margin=margin)
    bpy.ops.object.mode_set(mode='OBJECT')


def _retrieve_bakeable_materials(obj):
    """Retrieve all materials from the object that use nodes."""
    return [
        slot.material for slot in obj.material_slots
        if slot.material is not None and slot.material.use_nodes
    ]


def _build_final_material(obj, images):

    material = bpy.data.materials.new(EXPORT_MESH_NAME + "_Baked")
    material.use_nodes = True

    node_tree = material.node_tree
    node_tree.nodes.clear()

    output = node_tree.nodes.new("ShaderNodeOutputMaterial")
    output.location = (400, 0)
    bsdf = node_tree.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    node_tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    def _tex(image, non_color, y):
        node = node_tree.nodes.new("ShaderNodeTexImage")
        node.image = image
        node.location = (-700, y)
        if non_color:
            image.colorspace_settings.name = 'Non-Color'
        return node

    if 'base_color' in images:
        tex = _tex(images['base_color'], False, 400)
        node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])

    if 'metallic' in images:
        tex = _tex(images['metallic'], True, 150)
        node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Metallic"])

    if 'roughness' in images:
        tex = _tex(images['roughness'], True, -100)
        node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Roughness"])

    if 'normal' in images:
        tex = _tex(images['normal'], True, -350)
        normal_map = node_tree.nodes.new("ShaderNodeNormalMap")
        normal_map.location = (-350, -350)
        node_tree.links.new(tex.outputs["Color"], normal_map.inputs["Color"])
        node_tree.links.new(normal_map.outputs["Normal"], bsdf.inputs["Normal"])

    if 'emission' in images:
        tex = _tex(images['emission'], False, -600)
        node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Emission Color"])
        bsdf.inputs["Emission Strength"].default_value = 1.0

    obj.data.materials.clear()
    obj.data.materials.append(material)

    return material


def bake_materials(context, obj, props) -> str:
    """Bake all object materials into one combined atlased material. Returns a status message."""

    if not _retrieve_bakeable_materials(obj):
        return "No node-based materials to bake"

    scene = context.scene

    # Work on copies so the source materials are never modified.
    for slot in obj.material_slots:
        if slot.material is not None:
            slot.material = slot.material.copy()

    _ensure_uv_atlas(context, obj, props.uv_margin)

    # (key, label, bake pass, principled input to rewire or None, non-color data)
    channels = []
    if props.bake_base_color:
        channels.append(('base_color', 'BaseColor', 'EMIT', 'Base Color', False))
    if props.bake_metallic:
        channels.append(('metallic', 'Metallic', 'EMIT', 'Metallic', True))
    if props.bake_roughness:
        channels.append(('roughness', 'Roughness', 'ROUGHNESS', None, True))
    if props.bake_normal:
        channels.append(('normal', 'Normal', 'NORMAL', None, True))
    if props.bake_emission:
        channels.append(('emission', 'Emission', 'EMIT', None, False))

    if not channels:
        return "No bake maps selected"

    size = props.bake_resolution

    prev_engine = scene.render.engine
    scene.render.engine = 'CYCLES'
    prev_samples = scene.cycles.samples
    scene.cycles.samples = 8

    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    context.view_layer.objects.active = obj

    images = {}

    try:
        for key, label, pass_type, rewire_input, non_color in channels:

            image = _new_bake_image(
                f"{EXPORT_MESH_NAME}_{label}",
                size,
                non_color,
            )

            for material in _retrieve_bakeable_materials(obj):
                _set_bake_target(material, image)

            states = []
            if rewire_input:
                for material in _retrieve_bakeable_materials(obj):
                    states.append((material, _emit_rewire(material, rewire_input)))

            try:
                bpy.ops.object.bake(
                    type=pass_type,
                    margin=max(2, size // 256),
                    use_clear=True,
                )
            finally:
                for material, state in states:
                    _emit_restore(material, state)

            images[key] = image
    finally:
        for material in _retrieve_bakeable_materials(obj):
            node = material.node_tree.nodes.get(BAKE_TARGET_NODE)
            if node:
                material.node_tree.nodes.remove(node)

        scene.render.engine = prev_engine
        scene.cycles.samples = prev_samples

    _build_final_material(obj, images)

    directory = bpy.path.abspath(props.save_textures_dir) if props.save_textures_dir else ""
    if directory:
        os.makedirs(directory, exist_ok=True)

    for image in images.values():
        if directory:
            image.filepath_raw = os.path.join(directory, image.name + ".png")
            image.file_format = 'PNG'
            image.save()
        image.pack()

    return f"Baked {len(images)} map(s) into a combined material"
