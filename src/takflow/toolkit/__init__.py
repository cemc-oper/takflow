"""takflow toolkit — reusable CLI building blocks for workflow generators."""
from takflow.toolkit.credential import (
    CredentialContext,
    CredentialHookPoint,
    CredentialHookRegistry,
    get_credential_registry,
    register_credential_hook,
    render_credential,
    render_credential_template,
)
from takflow.toolkit.job import (
    generate_output_log_data,
    render_jobs_from_directory,
    render_single_job_file,
    set_build_info_provider,
)
from takflow.toolkit.resource import copy_resources_to_output, make_scripts_executable
from takflow.toolkit.util import (
    common_setting,
    script_cmd_var_name,
    script_cmd_value,
    set_scheduling,
    shell_job,
)

__all__ = [
    "copy_resources_to_output",
    "make_scripts_executable",
    "render_jobs_from_directory",
    "render_single_job_file",
    "generate_output_log_data",
    "set_build_info_provider",
    "render_credential",
    "render_credential_template",
    "register_credential_hook",
    "CredentialContext",
    "CredentialHookPoint",
    "CredentialHookRegistry",
    "get_credential_registry",
    "common_setting",
    "script_cmd_var_name",
    "script_cmd_value",
    "set_scheduling",
    "shell_job",
]
