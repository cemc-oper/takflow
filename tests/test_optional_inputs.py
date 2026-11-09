"""Optional capabilities select data once from the same effective config."""
from pathlib import Path

import pytest
from pydantic import Field, model_validator
import yaml

from takflow.application import ApplicationExtension, ResourceLayer, TemplateOutput
from takflow.build import BuildError, build, run_stage
from takflow.config import BaseWorkflowConfig, ConfigValidationError

from test_application import application as context_application, config_data
from test_build import application, data, put, resources


def test_optional_declarations_share_one_effective_config(tmp_path):
    calls = []

    class Config(BaseWorkflowConfig):
        feature: bool = False

        @model_validator(mode='after')
        def checked(self):
            calls.append('validate')
            return self

    def layers(config):
        calls.append(('layers', id(config)))
        return (ResourceLayer('feature', Path(config.workflow_repo_base_dir) / 'feature'),) if config.feature else ()

    def outputs(config):
        calls.append(('outputs', id(config)))
        return (TemplateOutput('config/feature.j2', 'config/feature.sh'),) if config.feature else ()

    def fragments(config):
        calls.append(('fragments', id(config)))
        return ('env/feature.sh',) if config.feature else ()

    def extension_layers(config):
        calls.append(('extension_layers', id(config)))
        return (ResourceLayer('extension', tmp_path / 'extension'),) if config.feature else ()

    def extension_outputs(config):
        calls.append(('extension_outputs', id(config)))
        return (TemplateOutput('config/site.j2', 'config/site.sh'),) if config.feature else ()

    app = context_application(tmp_path, config_type=Config, resource_layers=layers, outputs=outputs,
                              required_machine_fragments=fragments,
                              extensions=(ApplicationExtension('optional', resource_layers=extension_layers,
                                                               outputs=extension_outputs),))
    raw = config_data(feature=False, output_repo_base_dir=str(tmp_path / 'out'))
    with app.prepare(raw, overrides={'feature': True}, workflow_repo_base=tmp_path / 'parameter') as context:
        assert [p.name for p in context.paths.resource_layers] == ['base', 'feature', 'extension']
        assert context.paths.resource_layers[1].root == tmp_path / 'parameter/feature'
        assert [p.output for p in context.outputs] == ['config/feature.sh', 'config/site.sh']
        assert context.required_machine_fragments == ('env/feature.sh',)
        assert calls[0] == 'validate'
        assert sorted(name for name, _ in calls[1:]) == sorted(['layers', 'outputs', 'fragments', 'extension_layers', 'extension_outputs'])
        assert all(identity == id(context.config) for _, identity in calls[1:])
    assert raw['feature'] is False and not (tmp_path / 'out').exists()
    calls.clear()
    with app.prepare(raw) as context:
        assert len(context.paths.resource_layers) == 1 and context.outputs == ()
        assert context.required_machine_fragments == ()


def test_optional_layers_outputs_and_fragments_use_standard_stages(tmp_path, resources):
    class Config(BaseWorkflowConfig):
        feature: bool = False

    layer = tmp_path / 'feature'
    put(layer, 'scripts/on/task.sh', '#!/bin/bash\necho selected-feature\n')
    put(layer, 'config/feature.j2', 'FEATURE=enabled\n')
    put(layer, 'machine/site/env/feature.sh', 'FEATURE_MACHINE=1\n')
    app = application(resources, config_type=Config,
        resource_layers=lambda c: (ResourceLayer('feature', Path(c.workflow_repo_base_dir).parent / 'feature',
                                                required_inputs=('scripts/on/task.sh',)),) if c.feature else (),
        outputs=lambda c: (TemplateOutput('config/feature.j2', 'config/feature.sh'),) if c.feature else (),
        required_machine_fragments=lambda c: ('env/runtime.sh', 'env/feature.sh') if c.feature else ('env/runtime.sh',))
    raw = {**data(tmp_path / 'out'), 'feature': True}
    with app.prepare(raw) as context:
        result = build(context)
        assert result.complete
        assert 'selected-feature' in (context.paths.scripts_dir / 'on/task.sh').read_text()
        assert (context.paths.config_dir / 'feature.sh').read_text() == 'FEATURE=enabled\n'
        assert len([a for a in result.artifacts if a.kind == 'reference' and a.role == 'machine']) == 2
    with app.prepare(raw, overrides={'feature': False}) as context:
        result = build(context)
        assert result.complete and context.outputs == ()
        assert 'selected-feature' not in (context.paths.scripts_dir / 'on/task.sh').read_text()
        assert not any(a.path.endswith('/feature.sh') for a in result.artifacts)


def test_required_layer_inputs_cannot_fall_back_to_another_layer_or_stale_output(tmp_path, resources):
    put(resources, 'include/feature.h', '# wrong layer\n')
    source = tmp_path / 'selected'
    source.mkdir()
    output = tmp_path / 'out'
    put(output, 'include/feature.h', '# stale output\n')
    app = application(resources, resource_layers=(ResourceLayer('selected', source, required_inputs=('include/feature.h',)),))
    with app.prepare(data(output)) as context:
        with pytest.raises(BuildError) as caught:
            run_stage(context, 'resource')
        assert str(source / 'include/feature.h') in str(caught.value.original)
        assert caught.value.result.stages[0].status == 'failed'
    assert not (output / 'scripts').exists()
    assert (output / 'include/feature.h').read_text() == '# stale output\n'


def test_optional_machine_fragment_paths_are_checked_before_writing(tmp_path):
    app = context_application(tmp_path, required_machine_fragments=lambda c: ('../outside.sh',))
    with pytest.raises(ConfigValidationError, match='APPLICATION_RELATIVE_PATH'):
        with app.prepare(config_data(output_repo_base_dir=str(tmp_path / 'out'))):
            pass
    assert not (tmp_path / 'out').exists()


def test_optional_layers_receive_the_resolved_default_resource_factory(tmp_path):
    calls = []

    def root():
        calls.append('root')
        return tmp_path / 'package'

    def layers(config):
        calls.append(config.workflow_repo_base_dir)
        return (ResourceLayer('optional', Path(config.workflow_repo_base_dir) / 'optional'),)

    app = context_application(tmp_path, resources=root, resource_layers=layers)
    with app.prepare(config_data()) as context:
        assert context.paths.resource_layers[1].root == tmp_path / 'package/optional'
    assert calls == ['root', str(tmp_path / 'package')]


@pytest.mark.parametrize('origin', ['default', 'alias', 'canonical', 'override', 'model'])
@pytest.mark.parametrize('enabled', [False, True])
@pytest.mark.parametrize('owner', ['application', 'extension'])
def test_later_selectors_receive_resolved_preceding_layer_fields(tmp_path, monkeypatch, origin, enabled, owner):
    class Config(BaseWorkflowConfig):
        oper_root: str | None = Field(default=None, alias='legacy_oper')

        model_config = {'populate_by_name': True}

    source, caller = tmp_path / 'source', tmp_path / 'caller'
    source.mkdir()
    caller.mkdir()
    monkeypatch.chdir(caller)
    calls = []
    expected = tmp_path / 'package-oper' if origin == 'default' else source / 'oper'
    raw = config_data(output_repo_base_dir=str(tmp_path / 'out'), workflow_repo_base_dir='base',
                      observability={'enabled': enabled})
    if origin != 'default':
        raw['oper_root' if origin == 'canonical' else 'legacy_oper'] = 'oper'
    arguments = {'source_dir': source}
    if origin == 'override':
        arguments['overrides'] = {'oper_root': 'replacement'}
        expected = caller / 'replacement'

    def observation(config):
        calls.append(id(config))
        assert config.oper_root == str(expected)
        return (ResourceLayer('observation', Path(config.oper_root) / 'observability'),) if config.observability.enabled else ()

    oper = (ResourceLayer('oper', tmp_path / 'package-oper', config_field='oper_root'),)
    extensions = (ApplicationExtension('oper', resource_layers=oper),) if owner == 'extension' else ()
    app = context_application(tmp_path, config_type=Config,
        resource_layers=oper if owner == 'application' else (),
        extensions=(*extensions, ApplicationExtension('observation', resource_layers=observation)))
    path = source / 'input.yaml'
    path.write_text(yaml.safe_dump(raw))
    supplied = Config.model_validate(raw) if origin == 'model' else path
    with app.prepare(supplied, **arguments) as context:
        assert calls == [id(context.config)]
        assert [(layer.name, layer.root) for layer in context.paths.resource_layers] == [
            ('base', source / 'base'), ('oper', expected),
            *([('observation', expected / 'observability')] if enabled else []),
        ]
    assert raw.get('legacy_oper') == ('oper' if origin in ('alias', 'override', 'model') else None)
    if origin == 'model':
        assert supplied.oper_root == 'oper'
    assert not (tmp_path / 'out').exists()


@pytest.mark.parametrize('enabled', [False, True])
def test_selected_followup_layer_shares_final_sources_across_stages(tmp_path, resources, enabled):
    class Config(BaseWorkflowConfig):
        oper_root: str | None = None

    oper = tmp_path / 'oper'
    observation = oper / 'observation'
    job = (resources / 'jobs/on/task.sh.j2').read_text()
    for name, root in [('base', resources), ('oper', oper), *([('observation', observation)] if enabled else [])]:
        put(root, 'scripts/on/task.sh', f'#!/bin/bash\necho {name}\n')
        put(root, 'config/config.sh.j2', f'# config={name}\n')
        put(root, 'config/extra.j2', f'# extra={name}\n')
        put(root, 'fragments/shared.j2', f'# nested={name}\n')
        put(root, 'jobs/on/task.sh.j2', f'# job={name}\n' + job)
    put(resources, 'jobs/on/fallback.sh.j2', '#!/bin/bash\n{% include "fragments/shared.j2" %}\n')

    def layers(config):
        return (ResourceLayer('observation', Path(config.oper_root) / 'observation',
                              required_inputs=('scripts/on/task.sh',)),) if config.observability.enabled else ()

    app = application(resources, config_type=Config, outputs=(TemplateOutput('config/extra.j2', 'config/extra.sh'),),
        extensions=(ApplicationExtension('oper', resource_layers=(ResourceLayer('oper', oper, config_field='oper_root'),)),
                    ApplicationExtension('observation', resource_layers=layers)))
    raw = data(tmp_path / 'out', observability={'enabled': enabled})
    with app.prepare(raw) as context:
        result = build(context)
        assert result.complete
        names = ['base', 'oper', *(['observation'] if enabled else [])]
        assert [layer.name for layer in context.paths.resource_layers] == names
        selected, name = (observation, 'observation') if enabled else (oper, 'oper')
        for source, destination in [('scripts/on/task.sh', 'scripts/on/task.sh'),
                                    ('config/config.sh.j2', 'config/config.h'),
                                    ('config/extra.j2', 'config/extra.sh'),
                                    ('jobs/on/task.sh.j2', 'jobs/on/task.ecf')]:
            item = next(a for a in result.artifacts if a.path == str(context.paths.output_root / destination))
            if source.startswith('scripts'):
                assert [s['layer'] for s in item.sources] == names
                assert item.sources[-1]['path'] == str(selected / source)
            else:
                assert item.sources == [{'template': str(selected / source)}]
            assert name in (context.paths.output_root / destination).read_text()
        # A base-only job resolves its nested include from the final layer too.
        fallback = context.paths.jobs_dir / 'on/fallback.ecf'
        assert fallback.read_text() == f'#!/bin/bash\n# nested={name}\n'
        item = next(a for a in result.artifacts if a.path == str(fallback))
        assert item.sources == [{'template': str(resources / 'jobs/on/fallback.sh.j2')}]


def test_required_layer_input_paths_are_relative():
    with pytest.raises(ConfigValidationError, match='APPLICATION_RELATIVE_PATH'):
        ResourceLayer('feature', '/source', required_inputs=('../outside',))


@pytest.mark.parametrize('stage', ['job', 'workflow'])
def test_required_extra_config_outputs_are_stage_inputs(tmp_path, resources, stage):
    put(resources, 'config/feature.j2', 'FEATURE=enabled\n')
    app = application(resources, outputs=(TemplateOutput('config/feature.j2', 'config/feature.sh'),))
    with app.prepare(data(tmp_path / 'out')) as context:
        assert build(context).complete
        (context.paths.config_dir / 'feature.sh').unlink()
        with pytest.raises(BuildError) as caught:
            run_stage(context, stage)
        assert f'{stage}.input' in str(caught.value.original)
        assert not (context.paths.output_root / 'generation_manifest.json').exists()
