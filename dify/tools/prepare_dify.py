"""Prepare an existing clean checkout of official Dify 1.9.1; never starts Docker."""
import argparse
from pathlib import Path
import re
import secrets


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dify_checkout", type=Path)
    parser.add_argument("--model-host", help="Optional model API hostname to allow through Dify's egress proxy")
    args = parser.parse_args()
    root = args.dify_checkout.resolve()
    compose = (root / "docker/docker-compose.yaml").read_text(encoding="utf-8")
    if "langgenius/dify-api:1.9.1" not in compose:
        parser.error("Expected an official Dify 1.9.1 checkout.")
    env_file = root / "docker/.env"
    if env_file.exists():
        parser.error("docker/.env already exists; preserve it and follow README manual configuration.")
    proxy_file = root / "docker/ssrf_proxy/squid.conf.template"
    proxy = proxy_file.read_text(encoding="utf-8")
    model_acl = ""
    if args.model_host:
        if not re.fullmatch(r"[A-Za-z0-9.-]+", args.model_host):
            parser.error("model-host must be a hostname without scheme, port or path")
        model_acl = f"acl shop_model dstdomain {args.model_host}\nhttp_access allow localnet shop_model\n"
    marker = "http_access deny all"
    if marker not in proxy:
        parser.error("Unknown Squid template. No files changed.")
    allow = "acl shop_bridge dstdomain host.docker.internal\nhttp_access allow localnet shop_bridge\n" + model_acl
    env = (root / "docker/.env.example").read_text(encoding="utf-8")
    sandbox_key = secrets.token_urlsafe(32)
    updates = {"EXPOSE_NGINX_PORT": "8080", "EXPOSE_NGINX_SSL_PORT": "8443",
               "SECRET_KEY": secrets.token_urlsafe(42), "DB_PASSWORD": secrets.token_urlsafe(24),
               "REDIS_PASSWORD": secrets.token_urlsafe(24), "SANDBOX_API_KEY": sandbox_key,
               "CODE_EXECUTION_API_KEY": sandbox_key}
    for name, value in updates.items():
        env, count = re.subn(r"^" + name + r"=.*$", name + "=" + value, env, flags=re.MULTILINE)
        if count != 1:
            parser.error("Unknown .env.example field: " + name + "; no files changed.")
    proxy_file.with_suffix(".template.shop-backup").write_text(proxy, encoding="utf-8")
    proxy_file.write_text(proxy.replace(marker, allow + marker, 1), encoding="utf-8")
    env_file.write_text(env, encoding="utf-8")
    print("Prepared Dify 1.9.1 on port 8080; local secrets generated in docker/.env.")
    print("Docker has not been started. Follow README for the compose command.")


if __name__ == "__main__":
    main()
