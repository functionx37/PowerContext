"""Optional upstream DTO preflight. This is not an actual Dify import/runtime test."""
import argparse
import ast
from enum import StrEnum
import json
from pathlib import Path
import sys
import subprocess
import types
from types import SimpleNamespace
from urllib.request import urlopen
import yaml

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--compose-dir', type=Path, help='Optional prepared official Dify docker/ directory')
args = parser.parse_args()
sources = {
    'base-entities.py': 'api/core/workflow/nodes/base/entities.py',
    'code-entities.py': 'api/core/workflow/nodes/code/entities.py',
    'start-entities.py': 'api/core/workflow/nodes/start/entities.py',
    'end-entities.py': 'api/core/workflow/nodes/end/entities.py',
    'dify-http-entities.py': 'api/core/workflow/nodes/http_request/entities.py',
    'api-core-app-app_config-entities.py': 'api/core/app/app_config/entities.py',
}
(root / '.cache').mkdir(exist_ok=True)
for name, relative in sources.items():
    path = root / '.cache' / name
    if not path.exists():
        with urlopen('https://raw.githubusercontent.com/langgenius/dify/1.9.1/' + relative, timeout=30) as response:
            path.write_bytes(response.read())
module = types.ModuleType('dify_node_contracts')
sys.modules[module.__name__] = module
ns = module.__dict__
ns.update(ErrorStrategy=StrEnum('ErrorStrategy', {'DEFAULT_VALUE': 'default-value', 'FAIL_BRANCH': 'fail-branch'}),
          DefaultValueTypeError=ValueError,
          CodeLanguage=StrEnum('CodeLanguage', {'PYTHON3': 'python3', 'JAVASCRIPT': 'javascript'}),
          SegmentType=StrEnum('SegmentType', {s.upper().replace('[', '_').replace(']', ''): s for s in [
              'string', 'number', 'object', 'boolean', 'array[string]', 'array[number]', 'array[object]', 'array[boolean]']}),
          FileType=str, FileTransferMethod=str,
          dify_config=SimpleNamespace(HTTP_REQUEST_MAX_CONNECT_TIMEOUT=10, HTTP_REQUEST_MAX_READ_TIMEOUT=60,
                                     HTTP_REQUEST_MAX_WRITE_TIMEOUT=20, HTTP_REQUEST_NODE_SSL_VERIFY=True))

def load(name, selected=None):
    tree = ast.parse((root / '.cache' / name).read_text(encoding='utf-8'))
    if selected:
        # Keep the actual upstream class definitions, only providing their imported dependencies.
        tree.body = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name in selected]
    else:
        tree.body = [n for n in tree.body if not (isinstance(n, ast.ImportFrom) and (n.level or n.module.startswith(('core', 'configs'))))]
    exec(compile(tree, name, 'exec'), ns)

load('base-entities.py')
exec('from collections.abc import Sequence\nfrom typing import Any\nfrom pydantic import BaseModel,Field,field_validator', ns)
load('api-core-app-app_config-entities.py', {'VariableEntityType', 'VariableEntity'})
load('code-entities.py')
load('start-entities.py')
load('end-entities.py')
load('dify-http-entities.py')
models = {k:ns[v] for k,v in {'start':'StartNodeData','code':'CodeNodeData','end':'EndNodeData','http-request':'HttpRequestNodeData'}.items()}
checked = []
for p in sorted((root / 'dsl').glob('*.yml')):
    doc = yaml.safe_load(p.read_text(encoding='utf-8'))
    for node in doc['workflow']['graph']['nodes']:
        models[node['data']['type']].model_validate(node['data'])
        checked.append(p.name + ':' + node['id'])
print('PASS: actual upstream Dify 1.9.1 node DTO definitions validate all',len(checked),'nodes.')
report = {
    'target_dify_version':'1.9.1','dsl_version':'0.4.0',
    'official_node_data_models_checked':checked,
    'method':'Official node Pydantic class definitions; imported framework dependencies supplied as stand-ins. Not a full Dify runtime or import.',
    'dify_runtime_verified':False}
if args.compose_dir:
    directory = args.compose_dir.resolve()
    command = ['docker', '--config', str(root / '.runtime/docker-config'), 'compose',
               '--project-directory', str(directory), '--env-file', str(directory / '.env'),
               '-f', str(directory / 'docker-compose.yaml'), '-f', str(root / 'deploy/compose.override.yaml'),
               'config', '--quiet']
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError('Docker Compose configuration rejected: ' + result.stderr)
    report['official_compose_with_project_override_config_check'] = 'passed'
    print('PASS: official Compose configuration plus project override.')
(root / 'evidence').mkdir(exist_ok=True)
(root / 'evidence/deployment-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
