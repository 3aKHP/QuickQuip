"""Opt-in isolated Docker validation using an existing dependency-complete image.

QUICKQUIP_ENV_SMOKE_HOST selects an SSH Docker host; no production paths are mounted.
QUICKQUIP_ENV_SMOKE_IMAGE is required explicitly. No image is built or pulled.
"""
import io
import os
from pathlib import Path
import shlex
import subprocess
import tarfile
import textwrap

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv('QUICKQUIP_ENV_SMOKE_HOST') or not os.getenv('QUICKQUIP_ENV_SMOKE_IMAGE'),
    reason='Explicit isolated Docker host and image required',
)


def test_private_socket_rotation_and_compose_literal_roundtrip():
    host = os.environ['QUICKQUIP_ENV_SMOKE_HOST']
    image = os.environ['QUICKQUIP_ENV_SMOKE_IMAGE']
    def ssh(command, data=None):
        return subprocess.check_output(
            ['ssh', '-o', 'BatchMode=yes', host, command], input=data, timeout=120,
        )
    root = ssh('mktemp -d /tmp/quickquip-env-smoke.XXXXXX').decode().strip()
    assert root.startswith('/tmp/quickquip-env-smoke.')
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode='w:gz') as bundle:
        for path in Path('src').rglob('*.py'):
            bundle.add(path, arcname=str(path))
    ssh('tar -xzf - -C ' + shlex.quote(root), archive.getvalue())
    script = textwrap.dedent('''
        import json, pathlib, subprocess, time, uuid
        root = pathlib.Path(ROOT)
        name = 'env-smoke-' + uuid.uuid4().hex[:10]
        (root/'.env').write_text('EXAMPLE_API_KEY=old\\nPORT=8080\\n')
        (root/'read').mkdir(); (root/'write').mkdir()
        common = ['docker','run','--rm','-e','PYTHONPATH=/app/src',
                  '-v',str(root/'src')+':/app/src:ro']
        agent = subprocess.check_output(common + ['-d','--name',name,
            '-e','QUICKQUIP_ENV_ROOT=/host/project',
            '-e','QUICKQUIP_ENV_SOCKET=/read/control.sock',
            '-e','QUICKQUIP_ENV_WRITE_SOCKET=/write/control.sock',
            '-v',str(root)+':/host/project',
            '-v',str(root/'read')+':/read', '-v',str(root/'write')+':/write',
            IMAGE,'python','-m','quickquip.environment.transport']).decode().strip()
        try:
            for _ in range(100):
                if (root/'write/control.sock').exists():break
                time.sleep(.1)
            program = r"""
import asyncio, json
from quickquip.environment.transport import call
from quickquip.common import runtime_environment as runtime
from quickquip.llm.config import ProviderConfig
from quickquip.llm.provider import LLMRequest
from quickquip.llm.provider.openai import OpenAIProviderClient
from quickquip.llm.provider.base import LLMProviderError
from quickquip.llm.provider.retry import RetryPolicy
from quickquip.llm.client_fingerprints.catalog import get_catalog
from pathlib import Path
from dataclasses import replace
# protocol-only profile avoids unrelated installed profiles in the dependency image.
config=ProviderConfig(id='smoke',protocol='openai',base_url='https://example.test/v1',
 api_key_env='EXAMPLE_API_KEY',default_model='m',models=['m'])
async def run():
 request=LLMRequest(model='m',system_prompt='',messages=[],temperature=0,max_output_tokens=1)
 def load():
  snap=call('snapshot');runtime.install(snap['values'],snap['version']);return snap
 def save(changes,identity):
  return call('changes',{'expected_version':call('list')['version'],
    'request_id':identity,'changes':changes})
 load()
 with runtime.credential_scope():
  old=OpenAIProviderClient(config)
  save([{'name':'EXAMPLE_API_KEY','action':'replace','value':'rotated'}],'rotate')
  load()
  assert old._get_api_key()=='old'
 assert OpenAIProviderClient(config)._get_api_key()=='rotated'
 save([{'name':'NEW_API_KEY','action':'create','value':"a\\\\b'${PORT}"}],'create')
 snap=load()
 assert OpenAIProviderClient(
  replace(config,api_key_env='NEW_API_KEY'))._get_api_key()=="a\\\\b'${PORT}"
 public=json.dumps(call('list'))+json.dumps(call('operation',{'id':'create'}))
 assert 'rotated' not in public and "a\\\\b'${PORT}" not in public
 save([{'name':'EXAMPLE_API_KEY','action':'delete'}],'delete');load()
 try:OpenAIProviderClient(config)._get_api_key()
 except LLMProviderError:pass
 else:raise AssertionError('deleted credential returned')
 # A new process still receives the durable key, rather than stale injected env.
 print('rotation, new Provider, pinned task, deletion and public metadata passed')
asyncio.run(run())
"""
            consumer = common + ['-e','QUICKQUIP_ENV_SOCKET=/read/control.sock',
                '-e','QUICKQUIP_ENV_WRITE_SOCKET=/write/control.sock',
                '-e','EXAMPLE_API_KEY=stale-injected',
                '-v',str(root/'read')+':/read', '-v',str(root/'write')+':/write',
                IMAGE,'python','-c',program]
            subprocess.run(consumer, check=True)
            # The read endpoint refuses mutation even if a compromised Bot crafts JSON.
            read_only = r"""
import json,socket
s=socket.socket(socket.AF_UNIX);s.connect('/read/control.sock')
s.sendall(json.dumps({'action':'changes','body':{}}).encode()+b'\\n')
assert 'error' in json.loads(s.makefile('rb').readline())
"""
            subprocess.run(common+['-v',str(root/'read')+':/read:ro',IMAGE,
                                  'python','-c',read_only],check=True)
            (root/'compose.yml').write_text(
                f'services:\\n  test:\\n    image: {IMAGE}\\n    env_file: .env\\n')
            actual = subprocess.check_output(['docker','compose',
                '-f',str(root/'compose.yml'),'run','--rm','--no-deps','--pull','never',
                'test','python','-c',"import os; print(repr(os.environ['NEW_API_KEY']))"])
            assert actual.decode().strip()==repr("a\\\\b'${PORT}")
            assert subprocess.check_output(['docker','inspect',agent,'--format',
                                            '{{.RestartCount}}']).strip()==b'0'
            print('Compose literal roundtrip and read-only Bot boundary passed')
        finally:
            subprocess.run(['docker','stop',name],check=True,stdout=subprocess.DEVNULL)
    ''')
    script = '\n'.join(line[8:] if line.startswith('        ') else line
                       for line in script.splitlines())
    code = 'ROOT=' + repr(root) + '\nIMAGE=' + repr(image) + '\n' + script
    try:
        output = ssh('python3 -', code.encode())
        assert b'Compose literal roundtrip' in output
    finally:
        ssh('sudo -n python3 -c ' + shlex.quote(
            'import shutil; shutil.rmtree(' + repr(root) + ')'))
