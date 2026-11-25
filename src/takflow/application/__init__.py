"""Application declarations, inputs, and scoped build context."""
from takflow.application.context import BuildContext, BuildPaths, MachineContext
from takflow.application.declaration import Application, ApplicationBrand, ApplicationExtension
from takflow.application.inputs import (
    ComponentSelection, ResourceEntry, ResolvedResourceLayer, ResourceLayer, TemplateOutput,
)


__all__ = [
    "Application", "ApplicationBrand", "ApplicationExtension", "BuildContext", "BuildPaths",
    "ComponentSelection", "MachineContext", "ResourceLayer", "ResolvedResourceLayer",
    "ResourceEntry", "TemplateOutput",
]
