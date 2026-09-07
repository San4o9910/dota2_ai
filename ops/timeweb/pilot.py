"""Create/reuse exactly one NARMA pilot VM; deploy its private video service.

Timeweb bills ordinary VMs hourly. No period purchase, balance top-up, resizing,
paid deletion protection, DDoS or disk backups are requested here.
"""
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from uuid import UUID

from preflight import CheckError, NoRedirect, ORIGIN
from prebuilt_images import ImageError, prepare_bundle

NAME = "narma-vision-pilot-01"
MARKER = "NARMA managed pilot San4o9910/dota2_ai 2026-09-06"
PRESET = 6813
MAX_VM_MONTH_EQUIVALENT = 2760


def event(name, **values):
    print(json.dumps({"event": name, **values}), flush=True)


class Cloud:
    def __init__(self):
        self.token = os.environ.get("TIMEWEB_CLOUD_TOKEN", "").strip()
        if not 20 <= len(self.token) <= 16384 or any(c.isspace() for c in self.token):
            raise CheckError("missing_timeweb_secret")

    def call(self, method, path, payload=None):
        if method not in {"GET", "POST", "DELETE"} or not re.fullmatch(r"/api/v[12]/[a-z0-9/?=&-]+", path):
            raise CheckError("invalid_cloud_request")
        request = urllib.request.Request(ORIGIN + path, method=method,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Authorization":"Bearer " + self.token,
                "Content-Type":"application/json", "Accept":"application/json"})
        attempts = 3 if method == "GET" else 1
        for attempt in range(attempts):
            try:
                with urllib.request.build_opener(NoRedirect()).open(request, timeout=45) as response:
                    body = response.read(2*1024*1024+1)
                if len(body) > 2*1024*1024:
                    raise CheckError("cloud_response_too_large")
                return json.loads(body) if body.strip() else {}
            except urllib.error.HTTPError as error:
                # Read-only retries are bounded. Never repeat an ambiguous mutation.
                status = error.code
                error.close()
                if attempt + 1 < attempts and status in {429, 500, 502, 503, 504}:
                    time.sleep((2, 4)[attempt])
                    continue
                # Do not log bodies: VM/S3 responses may contain passwords and keys.
                raise CheckError("cloud_http_" + str(status) + "_" + method + "_" + path.split("?")[0]) from None
            except (urllib.error.URLError, TimeoutError):
                if attempt + 1 < attempts:
                    time.sleep((2, 4)[attempt])
                    continue
                raise CheckError("cloud_request_outcome_unknown") from None
            except OSError:
                raise CheckError("cloud_request_outcome_unknown") from None
            except (ValueError, UnicodeError):
                raise CheckError("cloud_response_invalid") from None

    def list(self, path, key):
        value = self.call("GET", path).get(key)
        if not isinstance(value, list):
            raise CheckError("cloud_list_schema")
        return value


def command(argv, *, input=None, timeout=180, bootstrap=False, phase="command"):
    # Never expose raw stdout/stderr from commands that may handle secrets.
    result = subprocess.run(argv, input=input, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=timeout)
    if result.returncode:
        for line in result.stdout.splitlines():
            if line.startswith(b'{"event": "prebuilt_images_failed"'):
                emit_image_failure(line)
            elif line.startswith(b'{"event": "https_failure"'):
                item=json.loads(line)
                if re.fullmatch('https_[a-z_]{1,80}',item.get('code','')):
                    event('https_failure',code=item['code'])
            elif line.startswith(b'{"event": "replay_activation_'):
                item=json.loads(line)
                if item.get('event')=='replay_activation_failure' and re.fullmatch('replay_[a-z_]{1,100}',item.get('code','')):
                    event('replay_activation_failure',code=item['code'])
                elif item.get('event')=='replay_activation_rollback' and all(x in ('worker','replay-worker') for x in item.get('restored_services',[])):
                    event('replay_activation_rollback',restored_services=item['restored_services'])
            elif line.startswith(b'{"event": "video_'):
                item=json.loads(line)
                if item.get('event') in ('video_pipeline_failure','video_activation_failure') and re.fullmatch('[A-Za-z_]{1,100}',item.get('code','')):
                    event(item['event'],code=item['code'])
                elif item.get('event')=='video_provider_failure':
                    event('video_provider_failure',error_class=item.get('class'),status=item.get('status'),category=item.get('category'))
            elif line.startswith(b'{"event": "provider_usage_diagnostic"'):
                # Already reduced to token counters and known modality enums on the VPS.
                item=json.loads(line)
                event('provider_usage_diagnostic',keys=item.get('keys'),usage=item.get('usage'),billing_status=item.get('billing_status'))
    if bootstrap:
        stages = {"lock", "cloud_init", "packages", "docker_firewall", "stop_worker", "prebuilt_images",
                  "build", "database_api", "readiness", "ready"}
        for line in (result.stdout + b"\n" + result.stderr).splitlines():
            vision_state = re.fullmatch(rb"NARMA_GEMINI_CHECK:(passed|previously_passed|previous_attempt_unresolved|failed)", line)
            if vision_state:
                event("gemini_vps_check", state=vision_state[1].decode(), scope="synthetic_transport_only")
            usage = re.fullmatch(rb"NARMA_GEMINI_USAGE:(total_input_tokens|total_output_tokens|total_thought_tokens|total_tokens):([0-9]{1,7})", line)
            if usage:
                event("gemini_vps_usage", metric=usage[1].decode(), tokens=int(usage[2]))
            match = re.fullmatch(rb"NARMA_BOOTSTRAP_(STAGE|FAILURE):([a-z_]+)(?::([0-9]{1,3}))?", line)
            if match and match[2].decode() in stages:
                event("bootstrap_" + match[1].decode().lower(), stage=match[2].decode(),
                      exit_code=int(match[3]) if match[3] else None)
            if line.startswith(b'{"event": "build_diagnostic"'):
                try:
                    item = json.loads(line)
                    if item.get('code') in {'dependency_rate_limited','dependency_network','dependency_denied',
                            'dependency_missing','dependency_integrity','source_missing','compile_error',
                            'disk_full','memory_limit','unclassified'}:
                        event('build_diagnostic', code=item['code'])
                except (ValueError, TypeError):
                    pass
            if line.startswith(b'{"event": "container_'):
                try:
                    item = json.loads(line)
                    if item.get("event") == "container_status" and item.get("service") in {"db","migrate","api","worker","replay-worker"}:
                        state = item.get("state")
                        health = item.get("health")
                        event("container_status", service=item["service"],
                            state=state if state in {"created","running","restarting","exited","paused","dead","removing"} else "unknown",
                            health=health if health in {"healthy","unhealthy","starting"} else "none",
                            exit_code=item.get("exit_code") if type(item.get("exit_code")) is int else None)
                    elif item.get("event") == "container_diagnostic" and item.get("service") in {"db","migrate","api"}:
                        allowed = {"permission_denied","read_only_filesystem","connection_refused","database_authentication_failed",
                            "dns_failed","missing_module","sql_syntax_error","database_operational_error","image_pull_rate_limit",
                            "image_pull_denied","out_of_memory"}
                        if item.get("code") in allowed:
                            event("container_diagnostic", service=item["service"], code=item["code"])
                except (ValueError, TypeError):
                    pass
    if result.returncode:
        phases = {"command", "release_directory", "source_transfer", "secret_install", "bootstrap", "gemini_check"}
        safe_phase = phase if phase in phases else "command"
        raise CheckError("command_failed_" + safe_phase + "_exit_" + str(result.returncode))
    return result.stdout


def emit_image_failure(line):
    try:
        item = json.loads(line)
        if item.get("event") == "prebuilt_images_failed" and re.fullmatch("prebuilt_[a-z_]{1,80}", item.get("code", "")):
            event("prebuilt_images_failed", code=item["code"])
    except (ValueError, TypeError):
        pass


def transfer_image_archive(argv, archive, timeout=900):
    """Stream the archive over authenticated SSH without buffering image bytes."""
    try:
        with Path(archive).open("rb") as source, tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
            result = subprocess.run(argv, stdin=source, stdout=output, stderr=errors, timeout=timeout)
            output.seek(0)
            for line in output.read(65536).splitlines():
                emit_image_failure(line)
            if result.returncode:
                raise CheckError("prebuilt_archive_transfer_failed")
    except (OSError, subprocess.TimeoutExpired):
        raise CheckError("prebuilt_archive_transfer_failed") from None


def address(server):
    for network in server.get("networks", []):
        if network.get("type") != "public":
            continue
        for value in network.get("ips", []):
            if value.get("type") == "ipv4":
                ip = ipaddress.ip_address(value["ip"])
                if ip.version == 4 and ip.is_global:
                    return str(ip)
    return None

def ensure_https(ssh,release,hostname,host):
    if {x[4][0] for x in socket.getaddrinfo(hostname,80,type=socket.SOCK_STREAM)}!={host}:
        raise CheckError('https_public_dns_mismatch')
    def remote(action):
        output=command(ssh+['python3 '+release+'/ops/timeweb/https.py '+action],timeout=1000)
        result=json.loads(output)
        if result.get('state')!='passed':
            raise CheckError('https_step_failed')
        event('https_configuration',step=action.split()[0],state='passed')
    remote('prepare '+shlex.quote(hostname)+' '+shlex.quote(host))
    opener=urllib.request.build_opener(NoRedirect())
    with opener.open('http://'+hostname+'/.well-known/acme-challenge/narma-probe',timeout=20) as response:
        if response.read(256)!=('narma-acme-'+host+'\n').encode():
            raise CheckError('https_public_challenge_mismatch')
    remote('issue')
    with opener.open('https://'+hostname+'/livez',timeout=20) as response:
        if json.loads(response.read(4096)).get('status')!='alive':
            raise CheckError('https_public_health_failed')
    try:
        opener.open('https://'+hostname+'/v1/videos',timeout=20)
        raise CheckError('https_unauthenticated_access')
    except urllib.error.HTTPError as error:
        if error.code!=401:
            raise CheckError('https_auth_check_failed') from None
    event('https_public_endpoint',origin='https://'+hostname,certificate_verified=True,anonymous_api_status=401)
    portal_origin='https://'+hostname
    for path,signature in (('/',b'NARMA VISION'),('/assets/portal.js',b'/api/session'),('/assets/portal.css',b'--surface')):
        with opener.open(portal_origin+path,timeout=20) as response:
            content=response.read(256*1024)
            if signature not in content or b'opendota' in content.lower():
                raise CheckError('standalone_portal_asset_invalid')
    with opener.open(portal_origin+'/api/session',timeout=20) as response:
        session=json.loads(response.read(8192))
        if session.get('authenticated') is not False or session.get('user') is not None:
            raise CheckError('standalone_portal_session_invalid')
    for request,expected in (
        (urllib.request.Request(portal_origin+'/api/videos'),401),
        (urllib.request.Request(portal_origin+'/api/auth/login',method='POST',data=b'{}',headers={'Origin':'https://invalid.example','Content-Type':'application/json'}),403)):
        try:
            opener.open(request,timeout=20)
            raise CheckError('standalone_portal_access_check_failed')
        except urllib.error.HTTPError as error:
            if error.code!=expected:
                raise CheckError('standalone_portal_access_check_failed') from None
    event('standalone_portal_ready',origin=portal_origin,anonymous_video_status=401,cross_origin_mutation_status=403,setup_required=session.get('setup_required'))


def selected_project(cloud):
    projects = cloud.list("/api/v1/projects?limit=100", "projects")
    candidates = [p for p in projects if re.sub(r"[^a-z0-9]", "", str(p.get("name", "")).lower())
                  in {"narma", "narmavision", "dota2ai"}]
    if len(candidates) == 1:
        return int(candidates[0]["id"])
    if len(projects) == 1:
        return int(projects[0]["id"])
    raise CheckError("project_selection_required")


def ensure_public_ip(cloud, server):
    inventory = cloud.call("GET", "/api/v1/floating-ips")
    ips = inventory.get("ips")
    if not isinstance(ips, list) or inventory.get("meta", {}).get("total") != len(ips):
        raise CheckError("floating_ip_inventory_incomplete")
    attached = [item for item in ips if item.get("resource_type") == "server"
                and item.get("resource_id") == server["id"]]
    if len(attached) == 1:
        event("existing_public_ip_binding", server_id=server["id"])
        return
    if attached:
        raise CheckError("multiple_public_ip_bindings")
    zone = server.get("availability_zone")
    # Region/preset and availability-zone identifiers are distinct in live API.
    # Use the validated VM's own zone rather than guessing it from "nl-1".
    if server.get("preset_id") != PRESET or not isinstance(zone, str) or not re.fullmatch(r"[a-z0-9-]{1,64}", zone):
        raise CheckError("unexpected_server_availability_zone")
    # Do not appropriate an address reserved for another purpose. A previous
    # ambiguous/failed allocation must be reconciled before allocating again.
    if any(item.get("availability_zone") == zone and item.get("resource_type") is None
           and item.get("resource_id") is None for item in ips):
        raise CheckError("unbound_public_ip_requires_reconciliation")
    created = cloud.call("POST", "/api/v1/floating-ips", {
        "availability_zone":zone, "is_ddos_guard":False})
    ip_id = str(UUID(created["ip"]["id"]))
    event("public_ip_created", ip_id=ip_id, server_id=server["id"])
    cloud.call("POST", f"/api/v1/floating-ips/{ip_id}/bind", {
        "resource_type":"server", "resource_id":server["id"]})
    event("public_ip_binding_requested", ip_id=ip_id, server_id=server["id"])


def main():
    cloud = Cloud()
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    sha = os.environ.get("GITHUB_SHA", "")
    if not 20 <= len(key) <= 16384 or any(c.isspace() for c in key):
        raise CheckError("missing_gemini_secret")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise CheckError("invalid_release")
    preset = next((p for p in cloud.list("/api/v1/presets/servers", "server_presets")
                   if p.get("id") == PRESET), None)
    if not preset or preset.get("location") != "nl-1" or preset.get("cpu") != 4 or preset.get("ram") != 8192:
        raise CheckError("pilot_preset_changed")
    price = preset.get("price")
    if type(price) not in (int, float) or not 0 < price <= MAX_VM_MONTH_EQUIVALENT:
        raise CheckError("pilot_price_exceeds_authorized_target")
    project = selected_project(cloud)
    servers = cloud.list("/api/v1/servers?limit=100", "servers")
    candidates = [s for s in servers if s.get("name") == NAME]
    if len(candidates) > 1 or (candidates and (candidates[0].get("comment") != MARKER
                                              or candidates[0].get("project_id") != project)):
        raise CheckError("existing_server_ownership_mismatch")
    if len(servers) >= 100:
        raise CheckError("server_inventory_needs_pagination")
    event("pilot_plan", preset_id=PRESET, cpu=4, ram_mb=8192, disk_mb=preset.get("disk"),
          vm_month_equivalent_rub=price, ipv4_month_estimate_rub=200,
          server_and_ip_day_estimate_rub=round((price+200)/30, 2),
          billing="hourly_balance_no_period_purchase", existing=bool(candidates))
    server_id = int(candidates[0]["id"]) if candidates else None
    if server_id is not None and candidates[0].get("preset_id") != PRESET:
        raise CheckError("existing_server_configuration_unverified")
    if server_id is None:
        # An existing, ownership-checked server does not depend on the OS catalog.
        options = cloud.list("/api/v1/os/servers", "servers_os")
        ubuntu = [item for item in options if str(item.get("name", "")).lower() == "ubuntu"
                  and str(item.get("version", "")) == "24.04"]
        if len(ubuntu) != 1:
            event("os_selection_required", options=[{k:i.get(k) for k in ("id","name","version")} for i in options])
            raise CheckError("ubuntu_2404_selection_required")
    ssh_id = None
    with tempfile.TemporaryDirectory(prefix="narma-pilot-") as tmp:
        temporary = Path(tmp)
        try:
            image_archive, image_manifest, image_metadata = prepare_bundle(sha, temporary / "images")
        except ImageError as error:
            raise CheckError(str(error)) from None
        event("prebuilt_images_prepared", release=sha, platform="linux/amd64",
            archive_bytes=image_metadata["archive_bytes"], source_tree=image_metadata["source_tree"])
        private = temporary/"key"
        command(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(private)])
        public = private.with_suffix(".pub").read_text().strip()
        try:
            item = cloud.call("POST", "/api/v1/ssh-keys", {
                "name":"narma-ci-" + os.environ.get("GITHUB_RUN_ID", "pilot"),
                "body":public, "is_default":False})
            ssh_id = int(item["ssh_key"]["id"])
            if server_id is None:
                cloud_init = """#cloud-config
ssh_pwauth: false
write_files:
  - path: /etc/ssh/sshd_config.d/70-narma.conf
    permissions: '0600'
    content: |
      PasswordAuthentication no
      KbdInteractiveAuthentication no
      PermitRootLogin prohibit-password
runcmd:
  - [systemctl, reload, ssh]
"""
                created = cloud.call("POST", "/api/v1/servers", {
                    "name":NAME, "hostname":NAME, "comment":MARKER,
                    "preset_id":PRESET, "os_id":ubuntu[0]["id"], "project_id":project,
                    "is_ddos_guard":False, "is_local_network":False,
                    "ssh_keys_ids":[ssh_id], "cloud_init":cloud_init})
                server_id = int(created["server"]["id"])
                event("server_created", server_id=server_id)
            else:
                cloud.call("POST", f"/api/v1/servers/{server_id}/ssh-keys", {"ssh_key_ids":[ssh_id]})
                event("server_reused", server_id=server_id)
            host = None
            ip_checked = False
            for attempt in range(50):
                server = cloud.call("GET", f"/api/v1/servers/{server_id}")["server"]
                host = address(server)
                if host:
                    break
                if server.get("status") == "on" and not ip_checked:
                    ensure_public_ip(cloud, server)
                    ip_checked = True
                if attempt % 6 == 0:
                    event("waiting_for_public_ip", server_id=server_id)
                time.sleep(10)
            if not host:
                raise CheckError("server_has_no_public_ipv4")
            # First-connection trust is explicit. The ephemeral known_hosts file
            # pins the first received host key for every subsequent SSH command.
            # It is not claimed to be independently verified against the provider.
            ssh = ["ssh", "-i", str(private), "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
                "-o", "StrictHostKeyChecking=accept-new", "-o", "UserKnownHostsFile="+str(temporary/"known_hosts"),
                "-o", "ConnectTimeout=8", "-o", "ServerAliveInterval=15", "root@"+host]
            for attempt in range(40):
                try:
                    command(ssh+["true"], timeout=15)
                    break
                except (CheckError, subprocess.TimeoutExpired):
                    if attempt == 39:
                        raise CheckError("ssh_not_ready") from None
                    if attempt % 6 == 0:
                        event("waiting_for_ssh", server_id=server_id)
                    time.sleep(10)
            event("ssh_ready", server_id=server_id)
            domains = cloud.call("GET", "/api/v1/domains?limit=100")
            event("technical_domain_inventory", domains=[{"fqdn":d.get("fqdn"),"linked_ip":d.get("linked_ip")}
                for d in domains.get("domains",[]) if d.get("is_technical") is True and d.get("linked_ip")==host])
            technical=[d.get('fqdn') for d in domains.get('domains',[]) if d.get('is_technical') is True and d.get('linked_ip')==host]
            hostname=technical[0] if len(technical)==1 else 'narma-'+host.replace('.','-')+'.sslip.io'
            release = "/opt/narma/releases/" + sha
            command(ssh+["mkdir -p " + release], timeout=30, phase="release_directory")
            archive = temporary/"source.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                bundle.add(image_manifest, arcname="images-manifest.json", recursive=False)
                if Path(".dockerignore").is_file():
                    bundle.add(".dockerignore", arcname=".dockerignore", recursive=False)
                for directory in (Path("services/video"), Path("services/replay"), Path("ops/timeweb")):
                    for path in directory.rglob("*"):
                        if not path.is_file() or path.is_symlink():
                            continue
                        if any(p in {"__pycache__", ".venv", "private-output", "target", "tooling", "native"} for p in path.parts):
                            continue
                        if path.name.startswith(".env") or path.suffix in {".key",".pem",".dem",".mp4",".mkv"}:
                            continue
                        bundle.add(path, arcname=str(path), recursive=False)
            command(ssh+["tar --no-same-owner -xzf - -C " + release], input=archive.read_bytes(), timeout=120, phase="source_transfer")
            # Secrets cross SSH only; none enters cloud-init, the source archive,
            # GitHub artifacts, command arguments or public logs.
            secret_input = json.dumps({"gemini_key":key, "release":sha}).encode()
            command(ssh+["python3 " + release + "/ops/timeweb/write_secrets.py"], input=secret_input, timeout=30, phase="secret_install")
            event("installing_private_services", server_id=server_id, release=sha)
            command(ssh+['python3 '+release+'/ops/timeweb/snapshot_worker_state.py '+sha],timeout=45)
            try:
                transfer_image_archive(ssh+["python3 " + release + "/ops/timeweb/prebuilt_images.py receive " + sha], image_archive)
                command(ssh+["python3 " + release + "/ops/timeweb/prebuilt_images.py install " + sha], timeout=650)
                event("prebuilt_images_installed", release=sha, immutable_ids_verified=True)
                command(ssh+["bash " + release + "/ops/timeweb/bootstrap.sh " + sha + " --prebuilt"], timeout=1200, bootstrap=True, phase="bootstrap")
                ensure_https(ssh,release,hostname,host)
            except Exception:
                try:
                    command(ssh+["python3 " + release + "/ops/timeweb/prebuilt_images.py rollback " + sha], timeout=150)
                    event("previous_images_and_api_restored")
                except Exception:
                    event("previous_images_and_api_restore_unconfirmed")
                try:
                    command(ssh+['python3 '+release+'/ops/timeweb/activate_replays.py '+sha+' '+hostname+' --rollback-only'],timeout=150)
                    event('previous_worker_restored_after_bootstrap_failure')
                except Exception:
                    event('previous_worker_restore_unconfirmed')
                raise
            event("private_services_ready", server_id=server_id, release=sha,
                public_application=False, worker_enabled=False,
                ready_checks=["postgresql","schema","media","private_api"])
            budget_output=command(ssh+["cd " + release + "/services/video && docker compose --project-name narma-video --env-file /opt/narma/secrets/video.env exec -T api python -m narma_video.budget"],timeout=30)
            state=json.loads(budget_output)
            event("global_video_allowance", enabled=state.get("enabled"),
                limit_microusd=state.get("limit_microusd"),spent_microusd=state.get("spent_microusd"),
                reserved_microusd=state.get("reserved_microusd"))
            # Start only the verified local replay worker. No synthetic paid job.
            output=command(ssh+['python3 '+release+'/ops/timeweb/activate_replays.py '+sha+' '+hostname],timeout=360)
            activated=json.loads(output)
            if (activated.get('event')!='replay_pipeline_ready'
                    or activated.get('fresh_worker_heartbeat') is not True
                    or activated.get('synthetic_paid_calls')!=0):
                raise CheckError('replay_pipeline_not_ready')
            event('replay_pipeline_ready',worker_enabled=True,fresh_worker_heartbeat=True,
                video_worker_stopped=True,synthetic_paid_calls=0)
            state=json.loads(command(ssh+["cd " + release + "/services/video && docker compose --project-name narma-video --env-file /opt/narma/secrets/video.env exec -T api python -m narma_video.budget"],timeout=30))
            event('post_activation_allowance',enabled=state.get('enabled'),
                limit_microusd=state.get('limit_microusd'),spent_microusd=state.get('spent_microusd'),
                reserved_microusd=state.get('reserved_microusd'))
            handoff=Path('ops/timeweb/bridge-handoff.json')
            if handoff.exists():
                expected=json.loads(handoff.read_text())
                if expected.get('server_id')!=server_id or expected.get('project_id')!=project:
                    raise CheckError('bridge_handoff_target_mismatch')
                output=command(ssh+['python3 '+release+'/ops/timeweb/bridge_handoff.py '+sha+' '+os.environ['GITHUB_RUN_ID']],timeout=30)
                encrypted=json.loads(output)
                if encrypted.get('event')!='encrypted_site_bridge' or not re.fullmatch('[A-Za-z0-9+/=]{684}',encrypted.get('ciphertext','')):
                    raise CheckError('bridge_handoff_invalid')
                event('encrypted_site_bridge',ciphertext=encrypted['ciphertext'],key_fingerprint=encrypted['key_fingerprint'],
                    release=sha,run_id=os.environ['GITHUB_RUN_ID'],server_id=server_id)
        finally:
            if ssh_id is not None:
                if server_id is not None:
                    try:
                        cloud.call("DELETE", f"/api/v1/servers/{server_id}/ssh-keys/{ssh_id}")
                    except CheckError:
                        event("ephemeral_binding_cleanup_unconfirmed", server_id=server_id)
                try:
                    cloud.call("DELETE", f"/api/v1/ssh-keys/{ssh_id}")
                except CheckError:
                    event("ephemeral_key_cleanup_unconfirmed")


if __name__ == "__main__":
    try:
        main()
    except CheckError as error:
        event("pilot_failed", code=str(error))
        sys.exit(1)
    except Exception:
        event("pilot_failed", code="unexpected_failure_no_sensitive_details_logged")
        sys.exit(1)
