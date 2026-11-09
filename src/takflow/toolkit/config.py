"""Configuration rendering for legacy application adapters.

New applications use the config stage of ``takflow.build``. This helper keeps
the legacy Jinja whitespace, undefined-value and executable-file behavior in
one place while their command interfaces are being migrated.
"""
from pathlib import Path

from jinja2 import Environment, FileSystemLoader


def render_config_template(config, template_path: str | Path, output_path: str | Path) -> None:
    """Render an existing config template with the historical file semantics.

    Missing templates raise ``TemplateNotFound``. An adapter promising an
    optional template must handle that policy before calling this helper.
    This is not a standard stage and never publishes a generation manifest.
    """
    template_path, output_path = Path(template_path), Path(output_path)
    environment = Environment(loader=FileSystemLoader(str(template_path.parent)))
    text = environment.get_template(template_path.name).render(config=config)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text)
    output_path.chmod(0o755)
