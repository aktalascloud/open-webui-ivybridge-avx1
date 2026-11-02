"""Identify the source-built application; retain every resolved library for audit."""
from importlib.metadata import PathDistribution
from pathlib import Path
import re


def resolved_requirements(target, project_name, project_version):
    normalize = lambda name: re.sub(r'[-_.]+', '-', name).lower()
    own_name = normalize(project_name)
    resolved = {}
    own = None
    # Read current installed metadata directly; Python3.12's discovery cache can
    # retain an earlier target directory listing after packages are installed.
    for info in sorted(Path(target).iterdir()):
        if info.suffix not in ('.dist-info', '.egg-info'):
            continue
        package = PathDistribution(info)
        name, version = package.metadata['Name'], package.version
        if not name or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', name) or not re.fullmatch(r'[A-Za-z0-9.!+_-]+', version):
            raise RuntimeError('Invalid resolved package metadata')
        key = normalize(name)
        if key in resolved:
            raise RuntimeError('Duplicate resolved package metadata: ' + key)
        resolved[key] = {'name': key, 'version': version}
        if key == own_name:
            if version != project_version:
                raise RuntimeError('Local application version differs from reviewed source')
            own = resolved[key]
    if own is None:
        raise RuntimeError('Locally built application metadata is missing')
    libraries = [value for key, value in sorted(resolved.items()) if key != own_name]
    if not libraries:
        raise RuntimeError('Resolved dependency inventory is empty')
    return libraries, own
