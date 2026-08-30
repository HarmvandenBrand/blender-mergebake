import logging

import bpy

from .bake_materials import bake_materials
from .constants import _EXPORT_MESH_NAME

logger = logging.getLogger(__name__)


# ------------------------------------------------------------
# Properties
# ------------------------------------------------------------

class FinalizerProperties(bpy.types.PropertyGroup):
    
    source_collection: bpy.props.PointerProperty(
        name="Source Collection",
        type=bpy.types.Collection
    ) # type: ignore
    recursive: bpy.props.BoolProperty(
        name="Recursive",
        description="Include objects from child collections",
        default=True,
        ) # type: ignore
    bake_resolution: bpy.props.IntProperty(
        name="Bake Resolution",
        description="Width and height of the baked textures in pixels",
        default=2048,
        min=16,
        max=8192,
        ) # type: ignore
    bake_base_color: bpy.props.BoolProperty(
        name="Base Color",
        default=True,
        ) # type: ignore
    bake_roughness: bpy.props.BoolProperty(
        name="Roughness",
        default=True,
        ) # type: ignore
    bake_metallic: bpy.props.BoolProperty(
        name="Metallic",
        default=True,
        ) # type: ignore
    bake_normal: bpy.props.BoolProperty(
        name="Normal",
        default=True,
        ) # type: ignore
    bake_emission: bpy.props.BoolProperty(
        name="Emission",
        default=True,
        ) # type: ignore
    uv_margin: bpy.props.FloatProperty(
        name="UV Margin",
        description="Spacing between UV islands in the bake atlas",
        default=0.02,
        min=0.0,
        max=1.0,
        ) # type: ignore
    save_textures_dir: bpy.props.StringProperty(
        name="Save Textures To",
        description="Optional folder to also write baked textures to disk (needed for FBX). Textures are always packed into the .blend file.",
        subtype='DIR_PATH',
        default="",
        ) # type: ignore



# ------------------------------------------------------------
# Operator
# ------------------------------------------------------------

class FINALIZER_OT_build_mesh(bpy.types.Operator):
    bl_idname = "finalizer_tools.build_mesh"
    bl_label = "Finalize Collection to Export Mesh"
    bl_description = "Duplicate objects, apply modifiers, and join"

    def execute(self, context: bpy.types.Context|None):

        if context is None:
            self.report({'ERROR'}, "Context is None")
            return {'CANCELLED'}

        props = context.scene.finalizer_tools

        collection : bpy.types.Collection = props.source_collection

        if collection is None:
            self.report(
                {'ERROR'},
                "No source collection selected"
            )
            return {'CANCELLED'}


        # Remove previous export object

        old = bpy.data.objects.get(_EXPORT_MESH_NAME)

        if old:
            bpy.data.objects.remove(
                old,
                do_unlink=True
            )

        # "[:]" necessary to avoid runtime errors while iterationg over all_objects.
        # See https://docs.blender.org/api/current/info_gotchas_crashes.html#collection-objects
        source_objects = collection.all_objects[:] if props.recursive else collection.objects

        # Duplicate objects

        duplicates = []

        for obj in source_objects:

            if obj.type != 'MESH':
                continue
            if not obj.visible_get():
                continue

            new_obj = obj.copy()

            if obj.data:
                new_obj.data = obj.data.copy()

            context.collection.objects.link(new_obj)

            duplicates.append(new_obj)



        # Apply modifiers

        bpy.ops.object.select_all(
            action='DESELECT'
        )

        for obj in duplicates:

            obj.select_set(True)
            context.view_layer.objects.active = obj

            bpy.ops.object.convert(
                target='MESH'
            )

            for mod in list(obj.modifiers):
                try:
                    bpy.ops.object.modifier_apply(
                        modifier=mod.name
                    )
                except Exception as e:
                    self.report({'ERROR'}, "Some modifiers could not be applied: " + str(e))
                    return {'CANCELLED'}

            obj.select_set(False)



        # Join

        bpy.ops.object.select_all(
            action='DESELECT'
        )

        for obj in duplicates:
            obj.select_set(True)

        context.view_layer.objects.active = duplicates[0]

        bpy.ops.object.join()

        export_obj = context.object
        export_obj.name = _EXPORT_MESH_NAME


        # Bake materials

        try:
            bake_message = bake_materials(context, export_obj, props)
        except Exception as e:
            self.report({'ERROR'}, "Baking failed: " + str(e))
            return {'CANCELLED'}


        self.report(
            {'INFO'},
            "Export mesh created. " + bake_message
        )

        return {'FINISHED'}



# ------------------------------------------------------------
# Panel
# ------------------------------------------------------------

class FINALIZER_PT_panel(bpy.types.Panel):

    bl_label = "Export Tools"
    bl_idname = "EXPORT_PT_tools"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Export Tools"


    def draw(self, context: bpy.types.Context):

        layout = self.layout

        props = context.scene.finalizer_tools

        layout.prop(
            props,
            "source_collection"
        )

        layout.prop(
            props,
            "recursive"
        )

        bake_box = layout.box()
        bake_box.label(text="Bake Maps")

        row = bake_box.row(align=True)
        row.prop(props, "bake_base_color", toggle=True)
        row.prop(props, "bake_metallic", toggle=True)
        row.prop(props, "bake_roughness", toggle=True)
        row = bake_box.row(align=True)
        row.prop(props, "bake_normal", toggle=True)
        row.prop(props, "bake_emission", toggle=True)

        bake_box.prop(props, "bake_resolution")
        bake_box.prop(props, "uv_margin")
        bake_box.prop(props, "save_textures_dir")

        layout.operator(
            "finalizer_tools.build_mesh",
            icon="EXPORT"
        )


# ------------------------------------------------------------
# Registration
# ------------------------------------------------------------

classes = (
    FinalizerProperties,
    FINALIZER_OT_build_mesh,
    FINALIZER_PT_panel,
)


def register():

    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.finalizer_tools = bpy.props.PointerProperty(
        type=FinalizerProperties
    )


def unregister():

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    del bpy.types.Scene.finalizer_tools



if __name__ == "__main__":
    register()