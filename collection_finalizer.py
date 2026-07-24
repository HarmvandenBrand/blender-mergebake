import logging

import bpy

logger = logging.getLogger(__name__)

_EXPORT_MESH_NAME = "EXPORT_MESH"


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


# ------------------------------------------------------------
# Operator
# ------------------------------------------------------------

class FINALIZER_OT_build_mesh(bpy.types.Operator):

    bl_idname = "finalizer_tools.build_mesh"
    bl_label = "Finalize Collection to Export Mesh"
    bl_description = "Duplicate objects, apply modifiers, and join"

    def execute(self, context: bpy.types.Context):

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
                    logger.error(e)

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


        self.report(
            {'INFO'},
            "Export mesh created"
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