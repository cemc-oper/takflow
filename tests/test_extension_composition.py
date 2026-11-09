"""Final application choices and local contributions share one prepared scope."""
from dataclasses import replace
import hashlib
import json

import pytest
from pydantic import model_validator

from takflow.application import ApplicationBrand, ApplicationExtension, TemplateOutput
from takflow.build import BuildError, build
from takflow.build_info import build_info_scope
from takflow.config import BaseWorkflowConfig, ConfigValidationError
from takflow.toolkit.credential import register_credential_hook, render_credential_template
from takflow.toolkit.job import _current_build_info_lines

from test_build import application, data, put, resources


SECRET = 'TC10_4_SYNTHETIC_PRIVATE_BODY'


@pytest.fixture(autouse=True)
def outer_brand():
    with build_info_scope(ApplicationBrand('foreign-domain', '1.0').lines()):
        yield


def assert_private(result, paths):
    public = json.dumps(result.as_dict())
    if result.manifest_path is not None:
        public += result.manifest_path.read_text()
    assert SECRET not in public
    for path in paths:
        artifact = next(item for item in result.artifacts if item.path == str(path))
        assert artifact.sensitive and artifact.mode == '0o600' and artifact.sha256 is None
        assert SECRET in path.read_text()
        assert hashlib.sha256(path.read_bytes()).hexdigest() not in public
        assert 'sha256' not in next(item for item in result.as_dict()['artifacts'] if item['path'] == str(path))


@pytest.mark.parametrize('enabled', [False, True])
def test_composed_choices_and_extension_data_share_effective_config(tmp_path, resources, enabled):
    calls = []

    class OperConfig(BaseWorkflowConfig):
        credential_selected: bool = False
        private_value: str = ''

        @model_validator(mode='after')
        def checked(self):
            calls.append(('validate', id(self)))
            return self

    def observe(name, config):
        calls.append((name, id(config)))
        assert config.credential_selected is enabled

    def brand(config):
        observe('brand', config)
        return ApplicationBrand('composed-domain', '1.0', config.workflow_name)

    def variables(config):
        observe('variables', config)
        return {'DOMAIN_NAME': config.workflow_name}

    def credential_enabled(config):
        observe('credential', config)
        return config.credential_selected

    def domain(context):
        observe('base-context', context.config)
        return {'base_value': context.config.workflow_name}

    def oper(context):
        observe('oper-context', context.config)
        assert not context.domain_context  # Contributions share the base view.
        return {'oper_value': context.config.private_value}

    def outputs(config):
        observe('oper-outputs', config)
        return (TemplateOutput('config/private.j2', 'config/private.sh', mode=0o600),) if config.credential_selected else ()

    def initialize():
        for priority, name in [(10, 'base'), (50, 'oper')]:
            def fragment(context, name=name):
                return render_credential_template(resources, context.credential, context.config, f'{name}.j2')
            register_credential_hook('credential.render', priority=priority)(fragment)

    put(resources, 'config/base.j2', '# base credential\n')
    put(resources, 'config/oper.j2', '# {{ base_value }} {{ variables.DOMAIN_NAME }} {{ brand.tool_name }}\nTOKEN={{ credential.token }}\n')
    put(resources, 'config/private.j2', 'PRIVATE={{ oper_value }}\n')
    put(resources, 'config/public.j2', '# {{ base_value }} {{ variables.DOMAIN_NAME }} {{ brand.tool_name }}\n')
    credential = put(tmp_path, 'credential.yaml', f'token: {SECRET}\n', 0o600)
    app = replace(application(resources), config_type=OperConfig, brand=brand, variables=variables,
                  context=domain, credential_enabled=credential_enabled,
                  outputs=(TemplateOutput('config/public.j2', 'config/public.sh'),),
                  extensions=(ApplicationExtension('oper', initialize=initialize, context=oper, outputs=outputs),))
    raw = data(tmp_path / 'out', credential_selected=not enabled)
    previous_brand = dict(_current_build_info_lines())
    with app.prepare(raw, overrides={'credential_selected': enabled, 'private_value': SECRET,
                                    'workflow_name': 'effective-name'}) as context:
        assert isinstance(context.config, OperConfig)
        assert context.template_context()['oper_value'] == SECRET
        assert context.variables['DOMAIN_NAME'] == 'effective-name'
        result = build(context, credential_file=credential if enabled else None)
        assert result.complete
        assert all(identity == id(context.config) for _, identity in calls)
        assert sorted(name for name, _ in calls) == sorted([
            'validate', 'brand', 'variables', 'base-context', 'oper-context', 'oper-outputs', 'credential'])
        public = context.paths.config_dir / 'public.sh'
        assert public.read_text() == '# effective-name effective-name composed-domain\n'
        private = [context.paths.config_dir / name for name in ('private.sh', 'credential.sh')]
        assert all(path.exists() is enabled for path in private)
        if enabled:
            text = private[1].read_text()
            assert text.index('# base credential') < text.index('TOKEN=')
            assert '# effective-name effective-name composed-domain' in text
            assert_private(result, private)
        else:
            assert SECRET not in result.manifest_path.read_text()
    assert dict(_current_build_info_lines()) == previous_brand
    assert raw['credential_selected'] is not enabled and 'private_value' not in raw


@pytest.mark.parametrize('conflict', ['config', 'brand', 'variables', 'include_raw', 'stdout', 'application', 'extension'])
def test_extension_context_conflicts_restore_brand_without_exposing_values(tmp_path, resources, conflict):
    app = application(resources)
    first = ApplicationExtension('first', context=lambda context: {'shared': SECRET})
    if conflict in ('application', 'extension'):
        app = replace(app, context=(lambda context: {'shared': SECRET}) if conflict == 'application' else None)
        extensions = (first,) if conflict == 'application' else (first, ApplicationExtension('second', context=lambda context: {'shared': SECRET}))
    else:
        extensions = (ApplicationExtension('conflict', context=lambda context: {conflict: SECRET}),)
    previous_brand = dict(_current_build_info_lines())
    with pytest.raises(ConfigValidationError) as caught:
        with replace(app, extensions=extensions).prepare(data(tmp_path / 'out')):
            pytest.fail('conflicting context entered the prepared scope')
    assert caught.value.diagnostics[0].code == 'APPLICATION_CONTEXT_CONFLICT'
    assert SECRET not in str(caught.value) + json.dumps([d.as_dict() for d in caught.value.diagnostics])
    assert dict(_current_build_info_lines()) == previous_brand
    assert not (tmp_path / 'out').exists()


@pytest.mark.parametrize('name', ['MACHINE_NAME', 'MACHINE_DIR', 'OUTPUT_REPO_BASE'])
def test_composed_variables_cannot_replace_framework_values(tmp_path, resources, name):
    app = application(resources, variables=lambda config: {name: SECRET})
    preparation = name != 'OUTPUT_REPO_BASE'
    with pytest.raises(ConfigValidationError if preparation else BuildError) as caught:
        with app.prepare(data(tmp_path / 'out')) as context:
            build(context)
    diagnostics = ([d.as_dict() for d in caught.value.diagnostics] if preparation else caught.value.result.diagnostics)
    assert any(d['code'] == ('APPLICATION_VARIABLE_CONFLICT' if preparation else 'BUILD_VARIABLE_CONFLICT') for d in diagnostics)
    assert SECRET not in str(caught.value) + json.dumps(diagnostics)
    assert not (tmp_path / 'out').exists()


@pytest.mark.parametrize('target', ['duplicate', 'config', 'credential', 'workflow', 'manifest', 'resource', 'job'])
def test_extension_output_collisions_keep_sensitive_partial_results_private(tmp_path, resources, target):
    output = tmp_path / 'out'
    put(output, 'generation_manifest.json', '{"complete": true}')
    put(resources, 'config/private.j2', SECRET)
    destinations = {'duplicate': 'config/private.sh', 'config': 'config/config.h',
                    'credential': 'config/credential.sh', 'workflow': 'test_workflow.def',
                    'manifest': 'generation_manifest.json', 'resource': 'scripts/on/task.sh',
                    'job': 'jobs/on/task.ecf'}
    item = TemplateOutput('config/private.j2', destinations[target], mode=0o600)
    extensions = (ApplicationExtension('private', outputs=(item,)),)
    if target == 'duplicate':
        extensions += (ApplicationExtension('second', outputs=(item,)),)
    app = application(resources, extensions=extensions)
    with app.prepare(data(output)) as context, pytest.raises(BuildError) as caught:
        build(context)
    result = caught.value.result
    assert not result.complete and result.manifest_path is None
    assert not (output / 'generation_manifest.json').exists()
    assert any(item['code'] == 'BUILD_OUTPUT_COLLISION' for item in result.diagnostics)
    assert next(s.name for s in result.stages if s.status == 'failed') == ('job' if target == 'job' else 'config')
    assert SECRET not in str(caught.value) + json.dumps(result.as_dict())
    if target == 'job':
        assert_private(result, [output / destinations[target]])
