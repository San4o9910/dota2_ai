"""Exercise Docker's actual runner egress boundary without provider requests."""
import json
import subprocess
import uuid


def run(args, timeout=30):
    result = subprocess.run(args, capture_output=True, timeout=timeout, check=True)
    return result.stdout.decode().strip()


def check():
    suffix = uuid.uuid4().hex[:12]
    private, public = 'hermes-private-' + suffix, 'hermes-canary-' + suffix
    runner, broker, canary = ('hermes-' + name + '-' + suffix for name in ('runner', 'broker', 'canary'))
    try:
        run(['docker', 'network', 'create', '--internal', private])
        run(['docker', 'network', 'create', public])
        run(['docker', 'run', '-d', '--name', broker, '--network', public,
             'narma-video-check', 'python', '-m', 'http.server', '8091'])
        run(['docker', 'network', 'connect', '--alias', 'hermes-broker', private, broker])
        run(['docker', 'run', '-d', '--name', canary, '--network', public,
             'narma-video-check', 'python', '-m', 'http.server', '8093'])
        external_ip = run(['docker', 'inspect', '--format',
                           '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}', canary])
        # The canary proves there is a listening destination outside the private
        # network, so a failure from the runner really tests routing isolation.
        run(['docker', 'exec', broker, 'python', '-c',
             """import socket,time
for attempt in range(10):
 try:
  socket.create_connection((%r,8093),2).close()
  break
 except OSError:
  time.sleep(0.5)
else:
 raise AssertionError('External canary did not become reachable')
""" % external_ip])
        run(['docker', 'run', '-d', '--name', runner, '--network', private,
             '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
             '--user', '10002:10002', '--memory', '1g', '--cpus', '1', '--pids-limit', '128',
             '--tmpfs', '/tmp:rw,nosuid,nodev,noexec,size=256m,mode=1777',
             '--env', 'HERMES_BROKER_URL=http://hermes-broker:8091/v1', 'narma-hermes-check'])
        probe = """import json,socket,time,urllib.request
for attempt in range(20):
 try:
  health=json.load(urllib.request.urlopen('http://127.0.0.1:8092/healthz',timeout=2))
  assert health['status']=='ready' and health['runtime_revision']=='9fd44b4dfc44138b9e5d5689acb56c438364ff7b'
  break
 except OSError:
  time.sleep(1)
else:
 raise AssertionError('Actual runner did not become ready')
urllib.request.urlopen('http://hermes-broker:8091/',timeout=5).close()
blocked=0
for host,port in %r:
 try:
  connection=socket.create_connection((host,port),3)
 except OSError:
  blocked+=1
 else:
  connection.close()
  raise AssertionError('Runner has external egress')
print(json.dumps({'broker_reachable':True,'external_destinations_blocked':blocked}))
""" % [(external_ip, 8093), ('generativelanguage.googleapis.com', 443), ('api.openai.com', 443),
       ('chatgpt.com', 443), ('auth.openai.com', 443)]
        evidence = json.loads(run(['docker', 'exec', runner, '/opt/hermes-venv/bin/python', '-c', probe], timeout=60))
        if evidence != {'broker_reachable': True, 'external_destinations_blocked': 5}:
            raise RuntimeError('Hermes network isolation not proved')
        print(json.dumps({'event': 'hermes_network_verified', **evidence}))
    finally:
        for name in (runner, broker, canary):
            subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=30)
        for name in (private, public):
            subprocess.run(['docker', 'network', 'rm', name], capture_output=True, timeout=30)


if __name__ == '__main__':
    check()
