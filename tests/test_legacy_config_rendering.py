"""The temporary config adapter preserves its legacy rendering contract."""
from types import SimpleNamespace
import stat

from jinja2 import TemplateNotFound
import pytest

from takflow.toolkit import render_config_template


def test_legacy_config_rendering_preserves_whitespace_permissions_and_failure(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    template = source / "config.j2"
    template.write_text("# {{ config.name }}\n{% if config.enabled %}\nexport VALUE=1\n{% endif %}\n{{ absent }}\n")
    output = tmp_path / "out/config/config.h"
    config = SimpleNamespace(name="example", enabled=True)
    assert render_config_template(config, template, output) is None
    assert output.read_text() == "# example\n\nexport VALUE=1\n\n"
    assert stat.S_IMODE(output.stat().st_mode) == 0o755
    output.chmod(0o600)
    with pytest.raises(TemplateNotFound):
        render_config_template(config, source / "missing.j2", output)
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert output.read_text() == "# example\n\nexport VALUE=1\n\n"
